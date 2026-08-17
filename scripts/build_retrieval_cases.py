import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from embedding.catalog_schema import parse_opening_hours
from embedding.text_utils import normalize_text


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_CATALOG_PATH = PROJECT_ROOT / "data" / "raw" / "food_raw.json"
OUTPUT_PATH = PROJECT_ROOT / "data" / "evaluation" / "retrieval_cases.json"

EXPECTED_GROUP_COUNTS = {
    "entity_lookup": 40,
    "opening_hours": 20,
    "no_accent": 15,
    "no_answer": 5,
}

# These districts currently have no verified OSM records in the promoted
# catalog. The validation step intentionally fails if that changes, so a
# maintainer must review and update the negative cases after a data refresh.
NO_ANSWER_CASES = (
    ("quán ăn ở Ba Vì", "Ba Vì"),
    ("quán ăn ở Hoài Đức", "Hoài Đức"),
    ("quán ăn ở Mỹ Đức", "Mỹ Đức"),
    ("quán ăn ở Quốc Oai", "Quốc Oai"),
    ("quán ăn ở Sơn Tây", "Sơn Tây"),
)


def read_catalog_rows() -> list[dict]:
    with RAW_CATALOG_PATH.open("r", encoding="utf-8") as file:
        rows = json.load(file)
    if not isinstance(rows, list):
        raise ValueError("food_raw.json must contain a JSON list.")
    return [
        row
        for row in rows
        if normalize_text(row.get("category")) == "am thuc"
    ]


def select_records(
    rows: list[dict],
    count: int,
    excluded_ids: set[str],
    require_opening_hours: bool = False,
) -> list[dict]:
    title_counts = Counter(normalize_text(row.get("title")) for row in rows)
    candidates = []
    for row in rows:
        record_id = str(row.get("id") or "").strip()
        title = str(row.get("title") or "").strip()
        district = str(row.get("district") or "").strip()
        opening_hours = str(row.get("opening_hours") or "").strip()
        if not record_id or not title or not district or record_id in excluded_ids:
            continue
        if title_counts[normalize_text(title)] != 1:
            continue
        if (
            require_opening_hours
            and parse_opening_hours(opening_hours)["opening_status"]
            != "known"
        ):
            continue
        candidates.append(row)

    by_district: dict[str, list[dict]] = defaultdict(list)
    for row in sorted(
        candidates,
        key=lambda item: (
            normalize_text(item["district"]),
            normalize_text(item["title"]),
            item["id"],
        ),
    ):
        by_district[row["district"]].append(row)

    selected = []
    district_names = sorted(by_district, key=normalize_text)
    while len(selected) < count:
        added = False
        for district in district_names:
            if by_district[district]:
                selected.append(by_district[district].pop(0))
                added = True
                if len(selected) == count:
                    break
        if not added:
            raise ValueError(
                f"Catalog does not contain {count} suitable evaluation records."
            )
    return selected


def build_positive_cases(
    group: str,
    prefix: str,
    records: list[dict],
    query_builder,
) -> list[dict]:
    return [
        {
            "id": f"{prefix}-{index:03d}",
            "group": group,
            "query": query_builder(record, index),
            "district": record["district"],
            "domain": "food",
            "expected_parent_ids": [record["id"]],
        }
        for index, record in enumerate(records, start=1)
    ]


def build_cases() -> list[dict]:
    rows = read_catalog_rows()
    used_ids: set[str] = set()

    entity_records = select_records(rows, 40, used_ids)
    used_ids.update(record["id"] for record in entity_records)

    opening_records = select_records(
        rows,
        20,
        used_ids,
        require_opening_hours=True,
    )
    used_ids.update(record["id"] for record in opening_records)

    no_accent_records = select_records(rows, 15, used_ids)

    cases = [
        *build_positive_cases(
            "entity_lookup",
            "entity",
            entity_records,
            lambda record, index: (
                f"địa chỉ {record['title']}"
                if index % 2
                else f"{record['title']} ở đâu"
            ),
        ),
        *build_positive_cases(
            "opening_hours",
            "opening",
            opening_records,
            lambda record, _: f"giờ mở cửa {record['title']}",
        ),
        *build_positive_cases(
            "no_accent",
            "no-accent",
            no_accent_records,
            lambda record, _: f"{normalize_text(record['title'])} o dau",
        ),
    ]

    for index, (query, district) in enumerate(NO_ANSWER_CASES, start=1):
        cases.append(
            {
                "id": f"no-answer-{index:03d}",
                "group": "no_answer",
                "query": query,
                "district": district,
                "domain": "food",
                "expected_parent_ids": [],
            }
        )

    return sorted(cases, key=lambda case: case["id"])


def validate_cases(cases: list[dict]) -> None:
    rows = read_catalog_rows()
    catalog = {str(row["id"]): row for row in rows}
    catalog_districts = {
        normalize_text(row.get("district"))
        for row in rows
    }

    ids = [case["id"] for case in cases]
    queries = [normalize_text(case["query"]) for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Evaluation case IDs must be unique.")
    if len(queries) != len(set(queries)):
        raise ValueError("Evaluation queries must be unique.")

    group_counts = Counter(case["group"] for case in cases)
    if dict(group_counts) != EXPECTED_GROUP_COUNTS:
        raise ValueError(f"Unexpected evaluation distribution: {group_counts}")

    for case in cases:
        expected_ids = case["expected_parent_ids"]
        if not expected_ids:
            if normalize_text(case["district"]) in catalog_districts:
                raise ValueError(
                    f"{case['id']} is no longer a valid no-answer case."
                )
            continue

        for parent_id in expected_ids:
            record = catalog.get(parent_id)
            if record is None:
                raise ValueError(f"{case['id']} references a missing record.")
            if normalize_text(record["district"]) != normalize_text(
                case["district"]
            ):
                raise ValueError(f"{case['id']} has a district mismatch.")


def write_cases(cases: list[dict]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump(cases, file, ensure_ascii=False, indent=2)
        file.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build deterministic retrieval cases from the food catalog."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check that the committed evaluation file is up to date.",
    )
    args = parser.parse_args()

    cases = build_cases()
    validate_cases(cases)
    if args.check:
        with OUTPUT_PATH.open("r", encoding="utf-8") as file:
            committed_cases = json.load(file)
        if committed_cases != cases:
            raise RuntimeError(
                "retrieval_cases.json is out of date. Run this script."
            )
    else:
        write_cases(cases)

    print(
        f"Validated {len(cases)} retrieval cases: "
        f"{dict(Counter(case['group'] for case in cases))}"
    )


if __name__ == "__main__":
    main()
