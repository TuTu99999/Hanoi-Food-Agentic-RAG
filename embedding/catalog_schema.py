import re
from typing import Any


PRICE_PATTERN = re.compile(
    r"^\s*(?P<minimum>[\d.]+)\s*đ?\s*-\s*"
    r"(?P<maximum>[\d.]+)\s*đ?\s*$",
    flags=re.IGNORECASE,
)
TIME_INTERVAL_PATTERN = re.compile(
    r"(?P<opens>\d{1,2}:\d{2})\s*-\s*"
    r"(?P<closes>\d{1,2}:\d{2})",
)


def parse_price_range(value: str | None) -> dict[str, Any]:
    """Normalize a food price range without losing its original value."""
    raw_value = str(value or "").strip()
    match = PRICE_PATTERN.fullmatch(raw_value)
    if not match:
        return {
            "price_min": None,
            "price_max": None,
            "price_currency": "VND",
            "price_status": "unknown",
        }

    try:
        minimum = int(match.group("minimum").replace(".", ""))
        maximum = int(match.group("maximum").replace(".", ""))
    except ValueError:
        return {
            "price_min": None,
            "price_max": None,
            "price_currency": "VND",
            "price_status": "invalid",
        }
    if minimum > maximum:
        return {
            "price_min": None,
            "price_max": None,
            "price_currency": "VND",
            "price_status": "invalid",
        }

    return {
        "price_min": minimum,
        "price_max": maximum,
        "price_currency": "VND",
        "price_status": "known",
    }


def parse_opening_hours(value: str | None) -> dict[str, Any]:
    """Normalize daily time intervals, including split and overnight shifts."""
    raw_value = str(value or "").strip()
    cleaned_value = re.sub(r"\([^)]*\)", "", raw_value)
    interval_parts = [
        part.strip()
        for part in cleaned_value.split("|")
        if part.strip()
    ]
    matches = [
        TIME_INTERVAL_PATTERN.fullmatch(part)
        for part in interval_parts
    ]
    if not matches or any(match is None for match in matches):
        return {
            "opening_intervals": [],
            "opening_status": "unknown",
            "opening_schedule_scope": "unknown",
        }

    intervals = []
    try:
        for match in matches:
            opens = _normalize_time(match.group("opens"))
            closes = _normalize_time(match.group("closes"))
            if opens == closes:
                raise ValueError("Equal opening and closing times are ambiguous")
            intervals.append(
                {
                    "opens": opens,
                    "closes": closes,
                    "closes_next_day": closes <= opens,
                }
            )
    except ValueError:
        return {
            "opening_intervals": [],
            "opening_status": "invalid",
            "opening_schedule_scope": "unknown",
        }

    return {
        "opening_intervals": intervals,
        "opening_status": "known",
        # The source has no weekday or holiday schedule.
        "opening_schedule_scope": "daily_assumed",
    }


def is_open_at(
    intervals: list[dict[str, Any]] | None,
    time_value: str | None,
) -> bool:
    """Return whether at least one normalized interval covers a local time."""
    if not intervals or not time_value:
        return False

    try:
        target = _time_to_minutes(_normalize_time(time_value))
    except (TypeError, ValueError):
        return False

    for interval in intervals:
        try:
            opens = _time_to_minutes(
                _normalize_time(str(interval["opens"]))
            )
            closes = _time_to_minutes(
                _normalize_time(str(interval["closes"]))
            )
        except (KeyError, TypeError, ValueError):
            continue

        if interval.get("closes_next_day"):
            if target >= opens or target < closes:
                return True
        elif opens <= target < closes:
            return True

    return False


def _normalize_time(value: str) -> str:
    hour, minute = value.split(":", maxsplit=1)
    hour_value = int(hour)
    minute_value = int(minute)
    if not 0 <= hour_value <= 23 or not 0 <= minute_value <= 59:
        raise ValueError("Invalid time")
    return f"{hour_value:02d}:{minute_value:02d}"


def _time_to_minutes(value: str) -> int:
    hour, minute = value.split(":", maxsplit=1)
    return int(hour) * 60 + int(minute)
