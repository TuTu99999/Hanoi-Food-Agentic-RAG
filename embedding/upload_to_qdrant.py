import argparse
import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import (
    CreateAlias,
    CreateAliasOperation,
    DeleteAlias,
    DeleteAliasOperation,
    Distance,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_VECTOR_FILE = PROJECT_ROOT / "data" / "final" / "hanoi_food_v1.json"
DEFAULT_COLLECTION = "hanoi_food_v1"
DEFAULT_ALIAS = "hanoi_food_current"
DEFAULT_EXPECTED_POINTS = 624
DEFAULT_EXPECTED_PARENTS = 418
POINT_ID_NAMESPACE = uuid.UUID("83eed46d-713b-4d5d-a8e8-caf7b61a98c8")

REQUIRED_PAYLOAD_FIELDS = (
    "chunk_id",
    "parent_id",
    "domain",
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
)

PAYLOAD_INDEXES = (
    ("domain", PayloadSchemaType.KEYWORD),
    ("parent_id", PayloadSchemaType.KEYWORD),
    ("title_normalized", PayloadSchemaType.KEYWORD),
    ("district_normalized", PayloadSchemaType.KEYWORD),
    ("category_normalized", PayloadSchemaType.KEYWORD),
    ("sub_category_normalized", PayloadSchemaType.KEYWORD),
    ("tags_normalized", PayloadSchemaType.KEYWORD),
    ("price_min", PayloadSchemaType.INTEGER),
    ("price_max", PayloadSchemaType.INTEGER),
)


def point_id_from_chunk_id(chunk_id):
    """Return the same Qdrant UUID every time a chunk is rebuilt."""
    return str(uuid.uuid5(POINT_ID_NAMESPACE, chunk_id))


def read_vector_file(path):
    if not path.exists():
        raise FileNotFoundError(f"Vector file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        rows = json.load(file)
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path} must contain a non-empty JSON list")
    return rows


def validate_vector_rows(
    rows,
    expected_point_count=None,
    expected_parent_count=None,
):
    chunk_ids = set()
    point_ids = set()
    vector_size = None

    for row_index, row in enumerate(rows):
        missing = [field for field in REQUIRED_PAYLOAD_FIELDS if field not in row]
        if missing:
            fields = ", ".join(missing)
            raise ValueError(f"Row {row_index} is missing payload fields: {fields}")
        if "vector" not in row:
            raise ValueError(f"Row {row_index} is missing vector")

        chunk_id = str(row["chunk_id"]).strip()
        if not chunk_id:
            raise ValueError(f"Row {row_index} has an empty chunk_id")
        if chunk_id in chunk_ids:
            raise ValueError(f"Duplicate chunk_id: {chunk_id}")
        chunk_ids.add(chunk_id)

        point_id = point_id_from_chunk_id(chunk_id)
        if point_id in point_ids:
            raise ValueError(f"Duplicate deterministic point id: {point_id}")
        point_ids.add(point_id)

        vector = row["vector"]
        if not isinstance(vector, list) or not vector:
            raise ValueError(f"{chunk_id} has an invalid vector")
        if vector_size is None:
            vector_size = len(vector)
        elif len(vector) != vector_size:
            raise ValueError(f"{chunk_id} has a different vector size")

        if row["domain"] != "food":
            raise ValueError(f"{chunk_id} must use the food domain")

    if (
        expected_point_count is not None
        and len(rows) != expected_point_count
    ):
        raise ValueError(
            f"Expected {expected_point_count} points, found {len(rows)}"
        )

    parent_count = len({row["parent_id"] for row in rows})
    if (
        expected_parent_count is not None
        and parent_count != expected_parent_count
    ):
        raise ValueError(
            f"Expected {expected_parent_count} food records, "
            f"found {parent_count}"
        )

    return vector_size


def build_payload(row):
    return {key: value for key, value in row.items() if key != "vector"}


def build_points(rows):
    for row in rows:
        yield PointStruct(
            id=point_id_from_chunk_id(row["chunk_id"]),
            vector=row["vector"],
            payload=build_payload(row),
        )


def create_payload_indexes(client, collection_name):
    for field_name, field_schema in PAYLOAD_INDEXES:
        client.create_payload_index(
            collection_name=collection_name,
            field_name=field_name,
            field_schema=field_schema,
            wait=True,
        )


def validate_uploaded_collection(client, collection_name, rows):
    expected_count = len(rows)
    actual_count = client.count(
        collection_name=collection_name,
        exact=True,
    ).count
    if actual_count != expected_count:
        raise RuntimeError(
            f"Upload validation failed: expected {expected_count} points, "
            f"found {actual_count}"
        )

    sample_rows = [rows[0], rows[len(rows) // 2], rows[-1]]
    sample_ids = [point_id_from_chunk_id(row["chunk_id"]) for row in sample_rows]
    records = client.retrieve(
        collection_name=collection_name,
        ids=sample_ids,
        with_payload=["chunk_id"],
        with_vectors=False,
    )
    returned_chunk_ids = {
        record.payload.get("chunk_id")
        for record in records
        if record.payload
    }
    expected_chunk_ids = {row["chunk_id"] for row in sample_rows}
    if returned_chunk_ids != expected_chunk_ids:
        raise RuntimeError("Upload validation failed: sample payloads do not match")


def switch_alias(client, collection_name, alias_name):
    aliases = client.get_aliases().aliases
    current = next(
        (alias for alias in aliases if alias.alias_name == alias_name),
        None,
    )

    if current and current.collection_name == collection_name:
        return

    operations = []
    if current:
        operations.append(
            DeleteAliasOperation(
                delete_alias=DeleteAlias(alias_name=alias_name)
            )
        )
    operations.append(
        CreateAliasOperation(
            create_alias=CreateAlias(
                collection_name=collection_name,
                alias_name=alias_name,
            )
        )
    )
    client.update_collection_aliases(
        change_aliases_operations=operations,
    )

    active = next(
        (
            alias
            for alias in client.get_aliases().aliases
            if alias.alias_name == alias_name
        ),
        None,
    )
    if not active or active.collection_name != collection_name:
        raise RuntimeError(f"Alias switch failed for {alias_name}")


def upload_vector_data(
    client,
    rows,
    collection_name,
    alias_name,
    switch_collection_alias=True,
    expected_point_count=None,
    expected_parent_count=None,
):
    vector_size = validate_vector_rows(
        rows,
        expected_point_count=expected_point_count,
        expected_parent_count=expected_parent_count,
    )

    if collection_name == alias_name:
        raise ValueError("Collection name and alias name must be different")
    if client.collection_exists(collection_name=collection_name):
        raise RuntimeError(
            f"Collection '{collection_name}' already exists. "
            "Use a new versioned collection name to avoid stale points."
        )

    client.create_collection(
        collection_name=collection_name,
        vectors_config=VectorParams(
            size=vector_size,
            distance=Distance.COSINE,
        ),
    )
    create_payload_indexes(client, collection_name)

    client.upload_points(
        collection_name=collection_name,
        points=build_points(rows),
        batch_size=64,
        max_retries=3,
        wait=True,
    )
    validate_uploaded_collection(client, collection_name, rows)

    if switch_collection_alias:
        switch_alias(client, collection_name, alias_name)

    return vector_size


def parse_args():
    parser = argparse.ArgumentParser(
        description="Upload a validated knowledge version and atomically switch its alias."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_VECTOR_FILE)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--alias", default=DEFAULT_ALIAS)
    parser.add_argument(
        "--expected-points",
        type=int,
        default=DEFAULT_EXPECTED_POINTS,
    )
    parser.add_argument(
        "--expected-parents",
        type=int,
        default=DEFAULT_EXPECTED_PARENTS,
    )
    parser.add_argument(
        "--qdrant-url",
        default=(
            os.getenv("QDRANT_URL")
            or (
                f"http://{os.getenv('QDRANT_HOST', '127.0.0.1')}:"
                f"{os.getenv('QDRANT_PORT', '6333')}"
            )
        ),
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("QDRANT_API_KEY"),
        help="Defaults to QDRANT_API_KEY. The value is never printed.",
    )
    parser.add_argument(
        "--no-alias-switch",
        action="store_true",
        help="Upload and validate the collection without activating it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the vector file without connecting to Qdrant.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.expected_points <= 0 or args.expected_parents <= 0:
        raise ValueError("Expected point and parent counts must be positive")
    vector_path = args.input.resolve()
    rows = read_vector_file(vector_path)
    vector_size = validate_vector_rows(
        rows,
        expected_point_count=args.expected_points,
        expected_parent_count=args.expected_parents,
    )

    print(
        f"Validated {len(rows)} points ({vector_size} dimensions) "
        f"for collection '{args.collection}'."
    )
    if args.dry_run:
        print("Dry-run completed. Qdrant was not contacted.")
        return

    client = QdrantClient(
        url=args.qdrant_url,
        api_key=args.api_key,
        timeout=60,
    )
    try:
        upload_vector_data(
            client=client,
            rows=rows,
            collection_name=args.collection,
            alias_name=args.alias,
            switch_collection_alias=not args.no_alias_switch,
            expected_point_count=args.expected_points,
            expected_parent_count=args.expected_parents,
        )
    finally:
        client.close()

    if args.no_alias_switch:
        print(
            f"Uploaded and validated '{args.collection}'. "
            f"Alias '{args.alias}' was not changed."
        )
    else:
        print(
            f"Uploaded and validated '{args.collection}'. "
            f"Alias '{args.alias}' now points to it."
        )


if __name__ == "__main__":
    main()
