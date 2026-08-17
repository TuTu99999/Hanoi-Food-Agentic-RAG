import math


MIN_RADIUS_KM = 0.2
MAX_RADIUS_KM = 20.0


def valid_coordinates(latitude: object, longitude: object) -> bool:
    try:
        latitude_value = float(latitude)
        longitude_value = float(longitude)
    except (TypeError, ValueError):
        return False

    return (
        math.isfinite(latitude_value)
        and math.isfinite(longitude_value)
        and -90 <= latitude_value <= 90
        and -180 <= longitude_value <= 180
    )


def distance_km(
    first_latitude: object,
    first_longitude: object,
    second_latitude: object,
    second_longitude: object,
) -> float | None:
    if not valid_coordinates(first_latitude, first_longitude):
        return None
    if not valid_coordinates(second_latitude, second_longitude):
        return None

    first_latitude_radians = math.radians(float(first_latitude))
    second_latitude_radians = math.radians(float(second_latitude))
    latitude_delta = second_latitude_radians - first_latitude_radians
    longitude_delta = math.radians(
        float(second_longitude) - float(first_longitude)
    )
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(first_latitude_radians)
        * math.cos(second_latitude_radians)
        * math.sin(longitude_delta / 2) ** 2
    )
    return 6371.0088 * 2 * math.asin(min(1.0, math.sqrt(haversine)))


def is_within_radius(
    place_latitude: object,
    place_longitude: object,
    user_latitude: object,
    user_longitude: object,
    radius_km: object,
) -> bool:
    try:
        radius_value = float(radius_km)
    except (TypeError, ValueError):
        return False

    distance = distance_km(
        user_latitude,
        user_longitude,
        place_latitude,
        place_longitude,
    )
    return distance is not None and distance <= radius_value
