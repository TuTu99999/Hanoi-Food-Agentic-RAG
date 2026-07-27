import argparse
import json
import os
import re
import unicodedata
from pathlib import Path

from dotenv import load_dotenv
from transformers import AutoTokenizer


load_dotenv()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
MAX_CHUNK_TOKENS = 90
OVERLAP_TOKENS = 15

DATASETS = (
    {
        "domain": "food",
        "input": PROJECT_ROOT / "data" / "raw" / "food_raw.json",
        "output": PROJECT_ROOT / "data" / "processed" / "food_chunks.json",
    },
    {
        "domain": "travel",
        "input": PROJECT_ROOT / "data" / "raw" / "travel_raw.json",
        "output": PROJECT_ROOT / "data" / "processed" / "travel_chunks.json",
    },
)

REQUIRED_FIELDS = (
    "id",
    "title",
    "category",
    "sub_category",
    "district",
    "address",
    "price_range",
    "opening_hours",
    "description",
    "tags",
)


def clean_text(value):
    """Return text with duplicate whitespace removed."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_for_filter(value):
    """Normalize Vietnamese text for exact Qdrant filters and reranking."""
    normalized = unicodedata.normalize("NFD", clean_text(value).casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.replace("đ", "d")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def count_tokens(tokenizer, text):
    return len(tokenizer.encode(text, add_special_tokens=False))


def split_sentences(text):
    cleaned = clean_text(text)
    if not cleaned:
        return []
    return [
        sentence
        for sentence in re.split(r"(?<=[.!?])\s+|[\r\n]+", cleaned)
        if sentence
    ]


def split_long_sentence(sentence, tokenizer, max_tokens):
    if count_tokens(tokenizer, sentence) <= max_tokens:
        return [sentence]

    parts = []
    current_words = []
    for word in sentence.split():
        candidate = clean_text(" ".join([*current_words, word]))
        if current_words and count_tokens(tokenizer, candidate) > max_tokens:
            parts.append(" ".join(current_words))
            current_words = [word]
        else:
            current_words.append(word)

        if count_tokens(tokenizer, " ".join(current_words)) > max_tokens:
            raise ValueError(
                f"One word exceeds the {max_tokens}-token body limit: {word}"
            )

    if current_words:
        parts.append(" ".join(current_words))
    return parts


def tail_with_token_limit(text, tokenizer, token_limit):
    """Return whole trailing words without breaking tokenizer subwords."""
    selected_words = []
    for word in reversed(text.split()):
        candidate_words = [word, *selected_words]
        candidate = " ".join(candidate_words)
        if count_tokens(tokenizer, candidate) > token_limit:
            break
        selected_words = candidate_words
    return " ".join(selected_words)


def add_overlap(previous_chunk, next_part, tokenizer, max_tokens, overlap_tokens):
    overlap_text = tail_with_token_limit(
        previous_chunk,
        tokenizer,
        overlap_tokens,
    )
    overlap_words = overlap_text.split()

    while overlap_words:
        overlap_text = " ".join(overlap_words)
        candidate = clean_text(f"{overlap_text} {next_part}")
        if count_tokens(tokenizer, candidate) <= max_tokens:
            return candidate
        overlap_words.pop(0)

    return next_part


def chunk_description(description, tokenizer, max_tokens, overlap_tokens):
    """Build sentence-aware chunks with a small token overlap."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be greater than zero")
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be between zero and max_tokens - 1")

    part_token_limit = max(max_tokens - overlap_tokens, 1)
    parts = []
    for sentence in split_sentences(description):
        parts.extend(
            split_long_sentence(
                sentence,
                tokenizer,
                part_token_limit,
            )
        )

    if not parts:
        return [""]

    chunks = []
    current = ""

    for part in parts:
        candidate = clean_text(f"{current} {part}")
        if not current or count_tokens(tokenizer, candidate) <= max_tokens:
            current = candidate
            continue

        chunks.append(current)
        current = add_overlap(
            previous_chunk=current,
            next_part=part,
            tokenizer=tokenizer,
            max_tokens=max_tokens,
            overlap_tokens=overlap_tokens,
        )

    if current:
        chunks.append(current)

    return chunks


def build_prefix(item):
    return clean_text(
        f"Tên: {item['title']}. "
        f"Địa chỉ: {item['address']}. "
        f"Quận: {item['district']}."
    )


def validate_item(item, domain, item_index):
    missing_fields = [field for field in REQUIRED_FIELDS if field not in item]
    if missing_fields:
        missing = ", ".join(missing_fields)
        raise ValueError(f"{domain}[{item_index}] is missing fields: {missing}")

    if not clean_text(item["id"]):
        raise ValueError(f"{domain}[{item_index}] has an empty id")
    if not clean_text(item["title"]):
        raise ValueError(f"{domain}[{item_index}] has an empty title")
    if not isinstance(item["tags"], list):
        raise ValueError(f"{domain}[{item_index}].tags must be a list")


def build_chunks(items, domain, tokenizer, max_tokens, overlap_tokens):
    chunks = []
    parent_ids = set()

    for item_index, raw_item in enumerate(items):
        validate_item(raw_item, domain, item_index)

        item = {key: clean_text(raw_item[key]) for key in REQUIRED_FIELDS if key != "tags"}
        item["tags"] = [clean_text(tag) for tag in raw_item["tags"] if clean_text(tag)]

        parent_id = item["id"]
        if parent_id in parent_ids:
            raise ValueError(f"Duplicate id in {domain}: {parent_id}")
        parent_ids.add(parent_id)

        prefix = build_prefix(item)
        prefix_tokens = count_tokens(tokenizer, prefix)
        body_token_limit = max_tokens - prefix_tokens
        if body_token_limit <= 0:
            raise ValueError(
                f"{parent_id} metadata uses {prefix_tokens} tokens, "
                f"which exceeds the {max_tokens}-token chunk limit"
            )

        body_overlap = min(overlap_tokens, max(body_token_limit - 1, 0))
        descriptions = chunk_description(
            description=item["description"],
            tokenizer=tokenizer,
            max_tokens=body_token_limit,
            overlap_tokens=body_overlap,
        )

        for chunk_index, description in enumerate(descriptions, start=1):
            vector_text = clean_text(f"{prefix} {description}")
            vector_tokens = count_tokens(tokenizer, vector_text)
            if vector_tokens > max_tokens:
                raise ValueError(
                    f"{parent_id} chunk {chunk_index} has {vector_tokens} tokens; "
                    f"the maximum is {max_tokens}"
                )

            chunks.append(
                {
                    "chunk_id": f"{parent_id}_chunk_{chunk_index:03d}",
                    "parent_id": parent_id,
                    "chunk_index": chunk_index,
                    "domain": domain,
                    "city": "Hà Nội",
                    "title": item["title"],
                    "title_normalized": normalize_for_filter(item["title"]),
                    "address": item["address"],
                    "address_normalized": normalize_for_filter(item["address"]),
                    "district": item["district"],
                    "district_normalized": normalize_for_filter(item["district"]),
                    "price_range": item["price_range"],
                    "opening_hours": item["opening_hours"],
                    "category": item["category"],
                    "category_normalized": normalize_for_filter(item["category"]),
                    "sub_category": item["sub_category"],
                    "tags": item["tags"],
                    "description": description,
                    "vector_text": vector_text,
                }
            )

    return chunks


def read_json(path):
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list")
    return data


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def process_dataset(dataset, tokenizer, max_tokens, overlap_tokens, dry_run=False):
    raw_items = read_json(dataset["input"])
    chunks = build_chunks(
        items=raw_items,
        domain=dataset["domain"],
        tokenizer=tokenizer,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
    )

    if not dry_run:
        write_json(dataset["output"], chunks)

    print(
        f"[{dataset['domain']}] {len(raw_items)} records -> {len(chunks)} chunks"
        + (" (dry-run)" if dry_run else f" -> {dataset['output']}")
    )
    return chunks


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create token-aware chunks for all food and travel data."
    )
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--max-tokens", type=int, default=MAX_CHUNK_TOKENS)
    parser.add_argument("--overlap-tokens", type=int, default=OVERLAP_TOKENS)
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        help="Load the tokenizer only from the local Hugging Face cache.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report chunk counts without writing files.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.max_tokens <= 0:
        raise ValueError("--max-tokens must be greater than zero")
    if args.overlap_tokens < 0 or args.overlap_tokens >= args.max_tokens:
        raise ValueError("--overlap-tokens must be between zero and max-tokens - 1")

    tokenizer = AutoTokenizer.from_pretrained(
        args.model,
        local_files_only=args.local_files_only,
    )

    all_chunk_ids = set()
    total_chunks = 0
    for dataset in DATASETS:
        chunks = process_dataset(
            dataset=dataset,
            tokenizer=tokenizer,
            max_tokens=args.max_tokens,
            overlap_tokens=args.overlap_tokens,
            dry_run=args.dry_run,
        )
        for chunk in chunks:
            if chunk["chunk_id"] in all_chunk_ids:
                raise ValueError(f"Duplicate chunk_id: {chunk['chunk_id']}")
            all_chunk_ids.add(chunk["chunk_id"])
        total_chunks += len(chunks)

    print(f"Completed: {total_chunks} unique chunks.")


if __name__ == "__main__":
    main()
