"""Import public Hanoi food-place metadata from OpenStreetMap.

The importer writes a review file by default. Promote that file to the raw
catalog only after checking the generated summary and a sample of records.
OpenStreetMap rarely contains menu prices or dish photos, so missing values
stay unknown instead of being guessed.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
import logging
import re
from pathlib import Path
import sys
import time
import unicodedata
from urllib.parse import unquote, urlparse

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "imports" / "osm_hanoi_food.json"
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "imports" / "osm_cache"
DEFAULT_OVERPASS_URLS = (
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
)
WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
OSM_COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
HANOI_BOUNDING_BOX = (20.45, 105.15, 21.45, 106.10)
INITIAL_TILE_ROWS = 4
INITIAL_TILE_COLUMNS = 4
MAX_TILE_SPLIT_DEPTH = 2
USER_AGENT = (
    "HanoiFoodRAG/1.0 "
    "(+https://github.com/TuTu99999/RAG_Food_And_Travel)"
)
FOOD_AMENITIES = (
    "restaurant",
    "fast_food",
    "cafe",
    "food_court",
    "ice_cream",
)
HANOI_DISTRICTS = (
    "Hoàn Kiếm",
    "Ba Đình",
    "Tây Hồ",
    "Cầu Giấy",
    "Hai Bà Trưng",
    "Đống Đa",
    "Thanh Xuân",
    "Hoàng Mai",
    "Long Biên",
    "Nam Từ Liêm",
    "Bắc Từ Liêm",
    "Hà Đông",
    "Sơn Tây",
    "Thanh Trì",
    "Gia Lâm",
    "Đông Anh",
    "Sóc Sơn",
    "Thạch Thất",
    "Quốc Oai",
    "Chương Mỹ",
    "Đan Phượng",
    "Hoài Đức",
    "Mê Linh",
    "Mỹ Đức",
    "Phú Xuyên",
    "Phúc Thọ",
    "Thanh Oai",
    "Thường Tín",
    "Ứng Hòa",
    "Ba Vì",
)
AMENITY_LABELS = {
    "restaurant": "Nhà hàng",
    "fast_food": "Đồ ăn nhanh",
    "cafe": "Quán cà phê",
    "food_court": "Khu ẩm thực",
    "ice_cream": "Quán kem",
}
CUISINE_LABELS = {
    "vietnamese": "Món Việt",
    "pho": "Phở",
    "noodle": "Mì/Bún/Phở",
    "coffee_shop": "Cà phê",
    "coffee": "Cà phê",
    "tea": "Trà",
    "ice_cream": "Kem",
    "bakery": "Bánh",
    "pizza": "Pizza",
    "burger": "Burger",
    "chicken": "Gà",
    "seafood": "Hải sản",
    "hotpot": "Lẩu",
    "sushi": "Sushi",
    "japanese": "Món Nhật",
    "korean": "Món Hàn",
    "chinese": "Món Trung",
    "thai": "Món Thái",
    "indian": "Món Ấn",
    "italian": "Món Ý",
    "french": "Món Pháp",
    "vegetarian": "Món chay",
}
DISTRICT_PREFIX_PATTERN = re.compile(
    r"^(quận|huyện|thị xã|district)\s+",
    flags=re.IGNORECASE,
)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
WIKIDATA_ID_PATTERN = re.compile(r"^Q\d+$")


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def console_safe(value: object) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return str(value).encode(encoding, errors="backslashreplace").decode(encoding)


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", clean_text(value).casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^\w]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


NORMALIZED_DISTRICTS = {
    normalize_text(district): district for district in HANOI_DISTRICTS
}


def split_values(value: object) -> list[str]:
    values = []
    for part in re.split(r"[;,]", clean_text(value)):
        item = clean_text(part).replace("_", " ")
        if item and item not in values:
            values.append(item)
    return values


def canonical_district(tags: dict) -> str:
    direct_keys = (
        "addr:district",
        "is_in:district",
        "district",
        "addr:county",
    )
    for key in direct_keys:
        value = DISTRICT_PREFIX_PATTERN.sub("", clean_text(tags.get(key)))
        district = NORMALIZED_DISTRICTS.get(normalize_text(value))
        if district:
            return district
    return "Chưa xác định"


def build_address(tags: dict, district: str) -> str:
    full_address = clean_text(tags.get("addr:full"))
    if full_address:
        return full_address

    street = clean_text(tags.get("addr:street"))
    house_number = clean_text(tags.get("addr:housenumber"))
    street_address = clean_text(f"{house_number} {street}")
    candidates = [
        street_address,
        tags.get("addr:subdistrict"),
        tags.get("addr:ward"),
        tags.get("addr:suburb"),
        district if district != "Chưa xác định" else None,
        "Hà Nội",
    ]
    parts = []
    normalized_parts = set()
    for candidate in candidates:
        part = clean_text(candidate)
        normalized = normalize_text(part)
        if not part or normalized in normalized_parts:
            continue
        parts.append(part)
        normalized_parts.add(normalized)
    return ", ".join(parts)


def address_source(tags: dict) -> str:
    if clean_text(tags.get("addr:full")):
        return "osm_addr_full"
    if clean_text(tags.get("addr:street")):
        return "osm_street"
    return "district_fallback"


def element_coordinates(element: dict) -> tuple[float | None, float | None]:
    location = element if element.get("type") == "node" else element.get("center", {})
    try:
        return float(location["lat"]), float(location["lon"])
    except (KeyError, TypeError, ValueError):
        return None, None


def cuisine_values(tags: dict) -> list[str]:
    return split_values(tags.get("cuisine"))


def cuisine_labels(cuisines: list[str]) -> list[str]:
    labels = []
    for cuisine in cuisines:
        label = CUISINE_LABELS.get(normalize_text(cuisine).replace(" ", "_"))
        label = label or cuisine.title()
        if label not in labels:
            labels.append(label)
    return labels


def build_description(
    title: str,
    amenity_label: str,
    district: str,
    cuisines: list[str],
) -> str:
    location = (
        f"{district}, Hà Nội"
        if district != "Chưa xác định"
        else "Hà Nội"
    )
    sentences = [f"{title} là {amenity_label.lower()} tại {location}."]
    if cuisines:
        sentences.append(
            "Loại ẩm thực được ghi nhận trên OpenStreetMap: "
            + ", ".join(cuisines)
            + "."
        )
    return " ".join(sentences)


def build_aliases(tags: dict, title: str) -> list[str]:
    aliases = []
    for key in ("alt_name:vi", "alt_name", "short_name", "brand"):
        for alias in split_values(tags.get(key)):
            if normalize_text(alias) == normalize_text(title):
                continue
            if alias not in aliases:
                aliases.append(alias)
    return aliases


def commons_title_from_value(value: object) -> str | None:
    raw_value = clean_text(value)
    if not raw_value:
        return None
    if raw_value.casefold().startswith("file:"):
        return "File:" + raw_value.split(":", maxsplit=1)[1]

    parsed = urlparse(raw_value)
    if parsed.scheme == "https" and parsed.hostname == "commons.wikimedia.org":
        marker = "/wiki/File:"
        if marker in parsed.path:
            filename = unquote(parsed.path.split(marker, maxsplit=1)[1])
            return f"File:{filename.replace('_', ' ')}"
    return None


def image_reference(tags: dict) -> tuple[str | None, str | None]:
    for key in ("wikimedia_commons", "image"):
        title = commons_title_from_value(tags.get(key))
        if title:
            return title, None

    wikidata_id = clean_text(tags.get("wikidata"))
    if WIKIDATA_ID_PATTERN.fullmatch(wikidata_id):
        return None, wikidata_id
    return None, None


def build_overpass_query(
    bounding_box: tuple[float, float, float, float],
) -> str:
    south, west, north, east = bounding_box
    amenities = "|".join(FOOD_AMENITIES)
    return f'''[out:json][timeout:90];
(
  nwr["amenity"~"^({amenities})$"]["name"]
    ({south},{west},{north},{east});
  nwr["amenity"~"^({amenities})$"]["name:vi"]
    ({south},{west},{north},{east});
);
out center tags qt;'''


def build_tiles(
    bounding_box: tuple[float, float, float, float],
    rows: int,
    columns: int,
) -> list[tuple[float, float, float, float]]:
    if rows <= 0 or columns <= 0:
        raise ValueError("Tile rows and columns must be greater than zero.")
    south, west, north, east = bounding_box
    latitude_step = (north - south) / rows
    longitude_step = (east - west) / columns
    return [
        (
            south + row * latitude_step,
            west + column * longitude_step,
            south + (row + 1) * latitude_step,
            west + (column + 1) * longitude_step,
        )
        for row in range(rows)
        for column in range(columns)
    ]


def split_tile(
    bounding_box: tuple[float, float, float, float],
) -> list[tuple[float, float, float, float]]:
    return build_tiles(bounding_box, rows=2, columns=2)


def validate_overpass_payload(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Overpass response must be a JSON object.")
    if clean_text(payload.get("remark")):
        raise ValueError("Overpass returned an incomplete response.")
    if not isinstance(payload.get("elements"), list):
        raise ValueError("Overpass response does not contain an element list.")
    return payload


def fetch_overpass_json(
    client: httpx.Client,
    endpoints: list[str],
    query: str,
    cache_dir: Path | None = None,
    refresh_cache: bool = False,
) -> dict:
    cache_path = None
    if cache_dir is not None:
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
        cache_path = cache_dir / f"overpass_{query_hash}.json"
        if cache_path.exists() and not refresh_cache:
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
                return validate_overpass_payload(payload)
            except (OSError, ValueError):
                logging.warning("Ignoring invalid Overpass cache: %s", cache_path)

    last_error = None
    for endpoint in endpoints:
        try:
            response = client.post(
                endpoint,
                data={"data": query},
                timeout=150,
            )
            response.raise_for_status()
            payload = validate_overpass_payload(response.json())
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )
            return payload
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            logging.warning("Overpass endpoint failed: %s", endpoint)
    raise RuntimeError("All configured Overpass endpoints failed.") from last_error


def fetch_overpass(
    client: httpx.Client,
    endpoints: list[str],
    request_delay_seconds: float = 0.5,
    cache_dir: Path | None = None,
    refresh_cache: bool = False,
) -> list[dict]:
    elements_by_id = {}

    def fetch_tile(
        bounding_box: tuple[float, float, float, float],
        depth: int,
    ) -> None:
        try:
            payload = fetch_overpass_json(
                client,
                endpoints,
                build_overpass_query(bounding_box),
                cache_dir=cache_dir,
                refresh_cache=refresh_cache,
            )
        except RuntimeError:
            if depth >= MAX_TILE_SPLIT_DEPTH:
                raise
            for smaller_tile in split_tile(bounding_box):
                fetch_tile(smaller_tile, depth + 1)
            return

        elements = payload.get("elements")
        if not isinstance(elements, list):
            raise ValueError(
                "Overpass response does not contain an element list."
            )
        for element in elements:
            key = (element.get("type"), element.get("id"))
            elements_by_id[key] = element
        time.sleep(max(request_delay_seconds, 0))

    initial_tiles = build_tiles(
        HANOI_BOUNDING_BOX,
        rows=INITIAL_TILE_ROWS,
        columns=INITIAL_TILE_COLUMNS,
    )
    for tile in initial_tiles:
        fetch_tile(tile, depth=0)
    return list(elements_by_id.values())


def fetch_wikidata_images(
    client: httpx.Client,
    wikidata_ids: list[str],
) -> dict[str, str]:
    resolved = {}
    unique_ids = list(dict.fromkeys(wikidata_ids))
    for start in range(0, len(unique_ids), 50):
        batch = unique_ids[start : start + 50]
        response = client.get(
            WIKIDATA_API_URL,
            params={
                "action": "wbgetentities",
                "format": "json",
                "props": "claims",
                "ids": "|".join(batch),
            },
            timeout=60,
        )
        response.raise_for_status()
        entities = response.json().get("entities", {})
        for entity_id, entity in entities.items():
            claims = entity.get("claims", {}).get("P18", [])
            if not claims:
                continue
            filename = (
                claims[0]
                .get("mainsnak", {})
                .get("datavalue", {})
                .get("value")
            )
            if isinstance(filename, str) and filename:
                resolved[entity_id] = f"File:{filename}"
    return resolved


def plain_metadata_text(value: object) -> str | None:
    text = HTML_TAG_PATTERN.sub("", html.unescape(clean_text(value)))
    return clean_text(text) or None


def fetch_commons_images(
    client: httpx.Client,
    commons_titles: list[str],
) -> dict[str, dict]:
    images = {}
    unique_titles = list(dict.fromkeys(commons_titles))
    for start in range(0, len(unique_titles), 50):
        batch = unique_titles[start : start + 50]
        response = client.get(
            COMMONS_API_URL,
            params={
                "action": "query",
                "format": "json",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "iiurlwidth": 960,
                "redirects": 1,
                "titles": "|".join(batch),
            },
            timeout=60,
        )
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})
        for page in pages.values():
            info_rows = page.get("imageinfo", [])
            if not info_rows:
                continue
            info = info_rows[0]
            image_url = clean_text(info.get("thumburl") or info.get("url"))
            parsed_url = urlparse(image_url)
            if parsed_url.scheme != "https" or parsed_url.hostname != "upload.wikimedia.org":
                continue

            metadata = info.get("extmetadata", {})
            license_name = clean_text(
                metadata.get("LicenseShortName", {}).get("value")
            )
            if not license_name:
                continue
            canonical_title = clean_text(page.get("title"))
            image_page_url = clean_text(info.get("descriptionurl"))
            images[canonical_title] = {
                "image_url": image_url,
                "image_source_url": image_page_url,
                "image_license": license_name,
                "image_attribution": plain_metadata_text(
                    metadata.get("Artist", {}).get("value")
                    or metadata.get("Credit", {}).get("value")
                ),
                "image_kind": "place",
            }
    return images


def to_catalog_record(
    element: dict,
    retrieved_at: str,
) -> dict | None:
    tags = element.get("tags") or {}
    amenity = clean_text(tags.get("amenity"))
    if amenity not in FOOD_AMENITIES:
        return None
    if clean_text(tags.get("access")).casefold() in {"no", "private"}:
        return None

    element_type = clean_text(element.get("type"))
    element_id = element.get("id")
    if element_type not in {"node", "way", "relation"} or not isinstance(element_id, int):
        return None

    title = clean_text(tags.get("name:vi") or tags.get("name"))
    if not title:
        return None

    latitude, longitude = element_coordinates(element)
    if latitude is None or longitude is None:
        return None

    district = canonical_district(tags)
    district_source = (
        "osm_address_tag" if district != "Chưa xác định" else "unknown"
    )
    cuisines = cuisine_values(tags)
    labels = cuisine_labels(cuisines)
    amenity_label = AMENITY_LABELS[amenity]
    sub_category = labels[0] if labels else amenity_label
    commons_title, wikidata_id = image_reference(tags)
    source_url = f"https://www.openstreetmap.org/{element_type}/{element_id}"
    tags_for_search = list(dict.fromkeys([amenity_label, sub_category, *labels]))

    record = {
        "id": f"osm_{element_type}_{element_id}",
        "title": title,
        "aliases": build_aliases(tags, title),
        "category": "Ẩm thực",
        "sub_category": sub_category,
        "district": district,
        "district_source": district_source,
        "address": build_address(tags, district),
        "address_source": address_source(tags),
        "latitude": latitude,
        "longitude": longitude,
        "cuisines": cuisines,
        "price_range": "N/A",
        "opening_hours": clean_text(tags.get("opening_hours")) or "N/A",
        "menu_items": [],
        "description": build_description(
            title=title,
            amenity_label=amenity_label,
            district=district,
            cuisines=labels,
        ),
        "tags": tags_for_search,
        "phone": clean_text(tags.get("contact:phone") or tags.get("phone")) or None,
        "website": clean_text(tags.get("contact:website") or tags.get("website")) or None,
        "image_url": None,
        "image_source_url": None,
        "image_license": None,
        "image_attribution": None,
        "image_kind": None,
        "source_name": "OpenStreetMap contributors",
        "source_url": source_url,
        "source_id": f"{element_type}/{element_id}",
        "retrieved_at": retrieved_at,
        "last_verified_at": None,
        "license": "ODbL 1.0",
        "license_url": OSM_COPYRIGHT_URL,
        "verification_status": "unverified",
    }
    record["_commons_title"] = commons_title
    record["_wikidata_id"] = wikidata_id
    return record


def attach_images(records: list[dict], client: httpx.Client) -> None:
    wikidata_ids = [
        record["_wikidata_id"]
        for record in records
        if record.get("_wikidata_id")
    ]
    wikidata_images = fetch_wikidata_images(client, wikidata_ids)
    for record in records:
        if not record.get("_commons_title") and record.get("_wikidata_id"):
            record["_commons_title"] = wikidata_images.get(record["_wikidata_id"])

    commons_titles = [
        record["_commons_title"]
        for record in records
        if record.get("_commons_title")
    ]
    commons_images = fetch_commons_images(client, commons_titles)
    for record in records:
        title = record.get("_commons_title")
        if title in commons_images:
            record.update(commons_images[title])


def clean_internal_fields(records: list[dict]) -> None:
    for record in records:
        record.pop("_commons_title", None)
        record.pop("_wikidata_id", None)


def build_summary(records: list[dict]) -> dict:
    districts = {}
    for record in records:
        district = record["district"]
        districts[district] = districts.get(district, 0) + 1
    return {
        "generated_at": records[0].get("retrieved_at") if records else None,
        "source_name": "OpenStreetMap contributors",
        "license": "ODbL 1.0",
        "license_url": OSM_COPYRIGHT_URL,
        "record_count": len(records),
        "district_count": len(districts),
        "unknown_district_count": districts.get("Chưa xác định", 0),
        "with_street_address_count": sum(
            record.get("address_source") != "district_fallback"
            for record in records
        ),
        "with_raw_opening_hours_count": sum(
            record.get("opening_hours") != "N/A" for record in records
        ),
        "with_cuisine_count": sum(
            bool(record.get("cuisines")) for record in records
        ),
        "with_image_count": sum(
            bool(record.get("image_url")) for record in records
        ),
        "districts": dict(sorted(districts.items())),
    }


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def import_osm_food(
    endpoints: list[str],
    output: Path,
    include_images: bool = True,
    request_delay_seconds: float = 0.5,
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
    refresh_cache: bool = False,
    include_unknown_districts: bool = False,
) -> tuple[list[dict], dict]:
    retrieved_at = datetime.now(timezone.utc).isoformat()
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    with httpx.Client(headers=headers, follow_redirects=True) as client:
        elements = fetch_overpass(
            client,
            endpoints,
            request_delay_seconds=request_delay_seconds,
            cache_dir=cache_dir,
            refresh_cache=refresh_cache,
        )
        records_by_id = {}
        for element in elements:
            record = to_catalog_record(element, retrieved_at)
            if record and (
                include_unknown_districts
                or record["district"] != "Chưa xác định"
            ):
                records_by_id[record["id"]] = record

        records = sorted(
            records_by_id.values(),
            key=lambda row: (
                normalize_text(row["district"]),
                normalize_text(row["title"]),
                row["id"],
            ),
        )
        if not records:
            raise RuntimeError(
                "OpenStreetMap returned no food places with a verified district."
            )
        if include_images and records:
            time.sleep(max(request_delay_seconds, 0))
            try:
                attach_images(records, client)
            except (httpx.HTTPError, ValueError) as exc:
                logging.warning("Image metadata could not be loaded: %s", exc)

    clean_internal_fields(records)
    summary = build_summary(records)
    write_json(output, records)
    write_json(output.with_suffix(".summary.json"), summary)
    return records, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import real Hanoi food places from OpenStreetMap."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--overpass-url",
        action="append",
        dest="overpass_urls",
        help="Override the default Overpass endpoints; may be repeated.",
    )
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument(
        "--include-unknown-districts",
        action="store_true",
        help="Keep places whose district cannot be verified from OSM tags.",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore cached Overpass tile responses and download them again.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records, summary = import_osm_food(
        endpoints=args.overpass_urls or list(DEFAULT_OVERPASS_URLS),
        output=args.output,
        include_images=not args.skip_images,
        refresh_cache=args.refresh_cache,
        include_unknown_districts=args.include_unknown_districts,
    )
    print(f"Imported {len(records)} Hanoi food places to {args.output}")
    print(console_safe(json.dumps(summary, ensure_ascii=False, indent=2)))


if __name__ == "__main__":
    main()
