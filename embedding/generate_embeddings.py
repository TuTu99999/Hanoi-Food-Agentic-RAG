import argparse
import hashlib
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
)
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "final" / "hanoi_food_osm_v1.json"

REQUIRED_FIELDS = (
    "chunk_id",
    "parent_id",
    "domain",
    "knowledge_version",
    "title",
    "title_normalized",
    "address",
    "address_normalized",
    "district",
    "district_normalized",
    "price_range",
    "price_min",
    "price_max",
    "price_currency",
    "price_status",
    "opening_hours",
    "opening_intervals",
    "opening_status",
    "opening_schedule_scope",
    "category",
    "category_normalized",
    "sub_category",
    "sub_category_normalized",
    "tags",
    "tags_normalized",
    "description",
    "vector_text",
    "source_name",
    "source_url",
    "retrieved_at",
    "last_verified_at",
    "license",
    "verification_status",
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


def json_sha256(data):
    serialized = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def load_and_validate_chunks(input_paths):
    chunks = []
    chunk_ids = set()
    knowledge_versions = set()

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
            if chunk["domain"] != "food":
                raise ValueError(
                    f"{input_path}[{row_index}] must use the food domain"
                )
            if not str(chunk["vector_text"]).strip():
                raise ValueError(f"{chunk_id} has empty vector_text")

            chunk_ids.add(chunk_id)
            knowledge_versions.add(str(chunk["knowledge_version"]).strip())
            chunks.append(chunk)

    if not chunks:
        raise ValueError("At least one food chunk is required")
    if "" in knowledge_versions or len(knowledge_versions) != 1:
        raise ValueError(
            "All chunks must use one non-empty knowledge_version"
        )

    return chunks


def generate_embeddings(
    chunks,
    model_name,
    batch_size,
    local_files_only=False,
):
    model = SentenceTransformer(
        model_name,
        local_files_only=local_files_only,
    )
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
        description="Generate one embedding file for the food catalog."
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
        "--local-files-only",
        action="store_true",
        help="Load the embedding model only from the local cache.",
    )
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
        f"(food={domains['food']})."
    )
    if args.dry_run:
        print("Dry-run completed. No model was loaded and no file was written.")
        return

    embedded_chunks, vector_size = generate_embeddings(
        chunks=chunks,
        model_name=args.model,
        batch_size=args.batch_size,
        local_files_only=args.local_files_only,
    )
    output_path = args.output.resolve()
    write_json(output_path, embedded_chunks)
    manifest_path = output_path.with_suffix(".manifest.json")
    write_json(
        manifest_path,
        {
            "schema_version": 1,
            "knowledge_version": chunks[0]["knowledge_version"],
            "domain": "food",
            "embedding_model": args.model,
            "vector_dimension": vector_size,
            "point_count": len(embedded_chunks),
            "parent_count": parent_count,
            "vector_artifact_sha256": json_sha256(embedded_chunks),
        },
    )
    print(
        f"Saved {len(embedded_chunks)} vectors ({vector_size} dimensions) "
        f"to {output_path}. Manifest: {manifest_path}."
    )


if __name__ == "__main__":
    main()
