import argparse
import json
import os
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer


load_dotenv()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
DEFAULT_INPUTS = (
    PROJECT_ROOT / "data" / "processed" / "food_chunks.json",
    PROJECT_ROOT / "data" / "processed" / "travel_chunks.json",
)
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "final" / "hanoi_knowledge_v2.json"

REQUIRED_FIELDS = (
    "chunk_id",
    "parent_id",
    "domain",
    "title",
    "address",
    "district",
    "district_normalized",
    "price_range",
    "opening_hours",
    "category",
    "category_normalized",
    "tags",
    "description",
    "vector_text",
)


def read_json(path):
    if not path.exists():
        raise FileNotFoundError(f"Chunk file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError(f"{path} must contain a JSON list")
    return data


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def load_and_validate_chunks(input_paths):
    chunks = []
    chunk_ids = set()

    for input_path in input_paths:
        for row_index, chunk in enumerate(read_json(input_path)):
            missing = [field for field in REQUIRED_FIELDS if field not in chunk]
            if missing:
                fields = ", ".join(missing)
                raise ValueError(f"{input_path}[{row_index}] is missing: {fields}")

            chunk_id = str(chunk["chunk_id"]).strip()
            if not chunk_id:
                raise ValueError(f"{input_path}[{row_index}] has an empty chunk_id")
            if chunk_id in chunk_ids:
                raise ValueError(f"Duplicate chunk_id: {chunk_id}")
            if chunk["domain"] not in {"food", "travel"}:
                raise ValueError(
                    f"{input_path}[{row_index}] has invalid domain: {chunk['domain']}"
                )
            if not str(chunk["vector_text"]).strip():
                raise ValueError(f"{chunk_id} has empty vector_text")

            chunk_ids.add(chunk_id)
            chunks.append(chunk)

    domains = Counter(chunk["domain"] for chunk in chunks)
    if not domains["food"] or not domains["travel"]:
        raise ValueError("Both food and travel chunks are required")

    return chunks


def generate_embeddings(chunks, model_name, batch_size):
    model = SentenceTransformer(model_name)
    texts = [chunk["vector_text"] for chunk in chunks]
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )

    if len(vectors) != len(chunks):
        raise RuntimeError("The embedding model returned an unexpected vector count")

    output = []
    vector_size = None
    for chunk, vector in zip(chunks, vectors):
        vector_list = vector.tolist()
        if vector_size is None:
            vector_size = len(vector_list)
        elif len(vector_list) != vector_size:
            raise RuntimeError("Embedding vectors do not have a consistent size")

        output.append({**chunk, "vector": vector_list})

    return output, vector_size


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate one embedding file for food and travel chunks."
    )
    parser.add_argument(
        "--inputs",
        nargs="+",
        type=Path,
        default=list(DEFAULT_INPUTS),
        help="Processed chunk JSON files.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=MODEL_NAME)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate chunk files without loading the model or writing vectors.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be greater than zero")

    input_paths = [path.resolve() for path in args.inputs]
    chunks = load_and_validate_chunks(input_paths)
    domains = Counter(chunk["domain"] for chunk in chunks)
    parent_count = len({chunk["parent_id"] for chunk in chunks})

    print(
        f"Validated {len(chunks)} chunks from {parent_count} records "
        f"(food={domains['food']}, travel={domains['travel']})."
    )
    if args.dry_run:
        print("Dry-run completed. No model was loaded and no file was written.")
        return

    embedded_chunks, vector_size = generate_embeddings(
        chunks=chunks,
        model_name=args.model,
        batch_size=args.batch_size,
    )
    output_path = args.output.resolve()
    write_json(output_path, embedded_chunks)
    print(
        f"Saved {len(embedded_chunks)} vectors ({vector_size} dimensions) "
        f"to {output_path}."
    )


if __name__ == "__main__":
    main()
