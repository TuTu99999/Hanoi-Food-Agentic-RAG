"""Collect a small, reviewable Foody Hanoi metadata sample.

This crawler intentionally:
- collects at most 50 public food-place records;
- excludes reviews, photos, usernames, phone numbers, and user content;
- waits between detail requests and stops on access denial;
- writes a separate import file instead of changing the production catalog.

Review Foody's current terms before every run. Public access does not grant a
right to republish or commercially reuse a bulk dataset.
"""

import argparse
import datetime
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "data" / "imports" / "foody_hanoi_poc.json"
)
BASE_URL = "https://www.foody.vn"
CITY_URL = f"{BASE_URL}/ha-noi"
LIST_URL = f"{BASE_URL}/__get/Place/HomeListPlace"
MAX_RECORDS = 50
MIN_DELAY_SECONDS = 2.0
INIT_DATA_MARKER = "var initData = "
USER_AGENT = (
    "RAGFoodPortfolioCrawler/0.1 "
    "(educational metadata POC; max 50 records)"
)
FORBIDDEN_OUTPUT_FIELDS = {
    "comment",
    "phone",
    "photo",
    "review",
    "user",
    "username",
}


class CrawlStoppedError(RuntimeError):
    """Raised when the source refuses access or no longer matches the parser."""


def normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text).strip()


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def console_safe(value: object) -> str:
    text = str(value)
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="backslashreplace").decode(encoding)


def strip_district_prefix(value: object) -> str:
    district = clean_text(value)
    return re.sub(
        r"^(quận|huyện|thị xã)\s+",
        "",
        district,
        flags=re.IGNORECASE,
    )


def format_money(value: object) -> str | None:
    try:
        amount = int(float(value))
    except (TypeError, ValueError):
        return None
    if amount < 0:
        return None
    return f"{amount:,}".replace(",", ".") + "đ"


def build_price_range(minimum: object, maximum: object) -> str:
    minimum_text = format_money(minimum)
    maximum_text = format_money(maximum)
    if not minimum_text or not maximum_text:
        return "N/A"
    return f"{minimum_text} - {maximum_text}"


def format_time_part(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    try:
        hours = int(value["Hours"])
        minutes = int(value["Minutes"])
    except (KeyError, TypeError, ValueError):
        return None
    if not 0 <= hours <= 23 or not 0 <= minutes <= 59:
        return None
    return f"{hours:02d}:{minutes:02d}"


def build_opening_hours(rows: object) -> tuple[str, list[int]]:
    if not isinstance(rows, list):
        return "N/A", []

    intervals = []
    source_days = []
    for row in rows:
        if not isinstance(row, dict) or row.get("IsDayOff"):
            continue
        opens = format_time_part(row.get("TimeOpen"))
        closes = format_time_part(row.get("TimeClose"))
        if not opens or not closes or opens == closes:
            continue
        interval = f"{opens} - {closes}"
        if interval not in intervals:
            intervals.append(interval)
        day = row.get("DayOfWeek")
        if isinstance(day, int) and day not in source_days:
            source_days.append(day)

    return (" | ".join(intervals) if intervals else "N/A"), source_days


def extract_init_data(html: str) -> dict:
    marker_index = html.find(INIT_DATA_MARKER)
    if marker_index < 0:
        raise CrawlStoppedError("Foody detail metadata marker was not found.")

    json_start = marker_index + len(INIT_DATA_MARKER)
    try:
        data, _end = json.JSONDecoder().raw_decode(html[json_start:])
    except json.JSONDecodeError as exc:
        raise CrawlStoppedError(
            "Foody detail metadata is no longer valid JSON."
        ) from exc
    if not isinstance(data, dict):
        raise CrawlStoppedError("Foody detail metadata has an invalid shape.")
    return data


def names_from_rows(rows: object, *, food_only: bool = False) -> list[str]:
    names = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if food_only and row.get("CategoryGroupKey") != "food":
            continue
        name = clean_text(row.get("Name"))
        if name and name not in names:
            names.append(name)
    return names


def build_full_address(data: dict) -> str:
    parts = [
        clean_text(data.get("Address")),
        clean_text(data.get("Area")),
        clean_text(data.get("District")),
        clean_text(data.get("City")),
    ]
    selected = []
    for part in parts:
        if not part:
            continue
        normalized = normalize_text(part)
        if any(normalized in normalize_text(existing) for existing in selected):
            continue
        selected.append(part)
    return ", ".join(selected)


def factual_description(record: dict) -> str:
    facts = [
        f"{record['title']} là địa điểm ẩm thực tại {record['district']}, Hà Nội."
    ]
    if record["sub_category"]:
        facts.append(f"Nhóm địa điểm: {record['sub_category']}.")
    if record["price_range"] != "N/A":
        facts.append(f"Khoảng giá tham khảo: {record['price_range']}.")
    if record["opening_hours"] != "N/A":
        facts.append(
            f"Giờ mở cửa được nguồn hiển thị: {record['opening_hours']}."
        )
    return " ".join(facts)


def to_catalog_record(data: dict, *, source_url: str, collected_at: str) -> dict:
    city = clean_text(data.get("City"))
    if normalize_text(city) != "ha noi":
        raise ValueError("Detail page is not a Hanoi place.")

    categories = names_from_rows(data.get("LstCategory"), food_only=True)
    cuisines = names_from_rows(data.get("Cuisines"))
    if not categories:
        raise ValueError("Detail page is not categorized as food.")

    title = clean_text(data.get("Name"))
    district = strip_district_prefix(data.get("District"))
    address = build_full_address(data)
    if not title or not district or not address:
        raise ValueError("Detail page is missing title, district, or address.")

    opening_hours, source_days = build_opening_hours(
        data.get("OpeningTime")
    )
    source_id = data.get("RestaurantID")
    if not isinstance(source_id, int) or source_id <= 0:
        raise ValueError("Detail page has an invalid restaurant id.")

    record = {
        "id": f"foody_{source_id}",
        "title": title,
        "category": "Ẩm thực",
        "sub_category": ", ".join(categories),
        "district": district,
        "address": address,
        "price_range": build_price_range(
            data.get("PriceMin"),
            data.get("PriceMax"),
        ),
        "opening_hours": opening_hours,
        "description": "",
        "tags": [*categories, *cuisines],
        "latitude": data.get("Latitude"),
        "longitude": data.get("Longtitude"),
        "source": "Foody.vn",
        "source_url": source_url,
        "source_restaurant_id": source_id,
        "opening_hours_source_days": source_days,
        "collected_at": collected_at,
    }
    record["description"] = factual_description(record)
    return record


def assert_safe_output(record: dict) -> None:
    lowered_keys = {key.casefold() for key in record}
    for forbidden in FORBIDDEN_OUTPUT_FIELDS:
        if any(forbidden in key for key in lowered_keys):
            raise ValueError(f"Forbidden output field detected: {forbidden}")


class FoodyClient:
    def __init__(self, timeout_seconds: float):
        self.client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "vi-VN,vi;q=0.9",
            },
        )

    def close(self) -> None:
        self.client.close()

    def _get(self, url: str, *, ajax: bool = False) -> httpx.Response:
        headers = {
            "Referer": CITY_URL,
            "Accept": (
                "application/json,text/plain,*/*"
                if ajax
                else "text/html,application/xhtml+xml"
            ),
        }
        if ajax:
            headers["X-Requested-With"] = "XMLHttpRequest"

        response = self.client.get(url, headers=headers)
        if response.status_code == 429:
            raise CrawlStoppedError(
                "Foody returned 429. Stop now and retry another day."
            )
        if response.status_code in {401, 403}:
            raise CrawlStoppedError(
                f"Foody denied access with HTTP {response.status_code}."
            )
        response.raise_for_status()
        return response

    def warm_city_session(self) -> None:
        response = self._get("/ha-noi")
        if "Foody.vn" not in response.text:
            raise CrawlStoppedError("Foody Hanoi landing page is unavailable.")

    def list_places(self, count: int) -> list[dict]:
        # Parameters are assigned separately to keep the endpoint readable.
        response = self.client.get(
            LIST_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "vi-VN,vi;q=0.9",
                "Referer": CITY_URL,
                "X-Requested-With": "XMLHttpRequest",
            },
            params={
                "page": 1,
                "lat": 21.028511,
                "lon": 105.804817,
                "count": count,
                "lastId": "",
                "ExcludeIds": "",
                "districtId": "",
                "cateId": "",
                "cuisineId": "",
                "isReputation": "",
                "isBooking": "",
                "isDelivery": "",
                "type": 1,
            },
        )
        if response.status_code == 429:
            raise CrawlStoppedError(
                "Foody returned 429. Stop now and retry another day."
            )
        if response.status_code in {401, 403}:
            raise CrawlStoppedError(
                f"Foody denied access with HTTP {response.status_code}."
            )
        response.raise_for_status()
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise CrawlStoppedError(
                "Foody list endpoint did not return JSON."
            ) from exc
        items = payload.get("Items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise CrawlStoppedError("Foody list endpoint has an invalid shape.")
        return items

    def detail(self, relative_url: str) -> tuple[dict, str]:
        absolute_url = urljoin(BASE_URL, relative_url)
        response = self._get(absolute_url)
        return extract_init_data(response.text), absolute_url


def collect(limit: int, delay_seconds: float, timeout_seconds: float) -> list[dict]:
    client = FoodyClient(timeout_seconds)
    collected_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    records = []
    seen = set()

    try:
        client.warm_city_session()
        # Ask for extra candidates because ads, duplicates, or incomplete
        # records can be skipped during detail validation.
        candidates = client.list_places(min(MAX_RECORDS, limit + 15))

        for candidate in candidates:
            if len(records) >= limit:
                break
            relative_url = clean_text(candidate.get("Url"))
            if not relative_url.startswith("/ha-noi/"):
                continue

            if records or seen:
                time.sleep(delay_seconds)

            try:
                detail, source_url = client.detail(relative_url)
                record = to_catalog_record(
                    detail,
                    source_url=source_url,
                    collected_at=collected_at,
                )
                dedupe_key = (
                    normalize_text(record["title"]),
                    normalize_text(record["address"]),
                )
                if dedupe_key in seen:
                    continue
                assert_safe_output(record)
            except ValueError as exc:
                print(console_safe(f"skip {relative_url}: {exc}"))
                continue

            seen.add(dedupe_key)
            records.append(record)
            print(
                console_safe(
                    f"[{len(records):02d}/{limit:02d}] {record['title']}"
                )
            )
    finally:
        client.close()

    if len(records) < limit:
        raise CrawlStoppedError(
            f"Only {len(records)} valid records were collected; "
            f"{limit} were requested."
        )
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect up to 50 public Foody Hanoi food metadata rows.",
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=3.0,
        help="Delay between detail pages; minimum 2 seconds.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--acknowledge-terms",
        action="store_true",
        help="Confirm that the operator reviewed Foody's current terms.",
    )
    args = parser.parse_args()

    if not 1 <= args.limit <= MAX_RECORDS:
        parser.error(f"--limit must be between 1 and {MAX_RECORDS}")
    if args.delay_seconds < MIN_DELAY_SECONDS:
        parser.error(
            f"--delay-seconds must be at least {MIN_DELAY_SECONDS:g}"
        )
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")
    if not args.acknowledge_terms:
        parser.error(
            "--acknowledge-terms is required after reviewing current terms"
        )
    return args


def main() -> int:
    args = parse_args()
    records = collect(
        limit=args.limit,
        delay_seconds=args.delay_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(records)} records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
