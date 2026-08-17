import math
from urllib.parse import urlencode

from embedding.text_utils import normalize_text


GOOGLE_MAPS_DIRECTIONS_URL = "https://www.google.com/maps/dir/"


def build_directions_url(
    latitude: object,
    longitude: object,
    *,
    address: object = None,
    address_source: object = None,
) -> str | None:
    """Prefer a street address and keep OSM coordinates as the fallback."""
    address_value = str(address or "").strip()
    has_specific_address = (
        address_source != "district_fallback"
        and len(normalize_text(address_value).split()) >= 4
    )
    if has_specific_address:
        query = urlencode({"api": "1", "destination": address_value})
        return f"{GOOGLE_MAPS_DIRECTIONS_URL}?{query}"

    try:
        latitude_value = float(latitude)
        longitude_value = float(longitude)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(latitude_value) or not math.isfinite(longitude_value):
        return None
    if not -90 <= latitude_value <= 90 or not -180 <= longitude_value <= 180:
        return None

    destination = f"{latitude_value:.7f},{longitude_value:.7f}"
    query = urlencode({"api": "1", "destination": destination})
    return f"{GOOGLE_MAPS_DIRECTIONS_URL}?{query}"


def append_directions_links(answer: str, documents: list[dict]) -> str:
    """Append directions only for places that appear in the final answer."""
    cleaned_answer = str(answer or "").strip()
    if not cleaned_answer or not documents:
        return cleaned_answer

    normalized_answer = normalize_text(cleaned_answer)
    directions = []
    seen_places = set()

    for document in documents:
        title = str(document.get("title") or "").strip()
        address = str(document.get("address") or "").strip()
        normalized_title = normalize_text(title)
        normalized_address = normalize_text(address)
        address_is_specific = (
            len(normalized_address.split()) >= 4
            and document.get("address_source") != "district_fallback"
        )
        is_mentioned = (
            bool(normalized_title) and normalized_title in normalized_answer
        ) or (
            address_is_specific and normalized_address in normalized_answer
        )
        if not is_mentioned:
            continue

        url = build_directions_url(
            document.get("latitude"),
            document.get("longitude"),
            address=address,
            address_source=document.get("address_source"),
        )
        place_key = (
            document.get("parent_id")
            or document.get("source_id")
            or (title, address, url)
        )
        if not url or place_key in seen_places or url in cleaned_answer:
            continue

        seen_places.add(place_key)
        label = " — ".join(part for part in (title, address) if part)
        directions.append(f"- [{_escape_markdown(label)}]({url})")

    if not directions:
        return cleaned_answer

    return (
        f"{cleaned_answer}\n\n"
        "**Chỉ đường từ vị trí hiện tại:**\n"
        + "\n".join(directions)
    )


def _escape_markdown(value: str) -> str:
    return value.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
