from __future__ import annotations

from math import asin, cos, radians, sin, sqrt
import math
import re


EARTH_RADIUS_M = 6_371_000
LEVEL_WHITELIST = {
    "兴趣点",
    "公交地铁站点",
    "门牌号",
    "门址",
    "道路交叉路口",
    "住宅区",
    "热点商圈",
}
LEVEL_RANK = {
    "门牌号": 6,
    "门址": 6,
    "公交地铁站点": 5,
    "兴趣点": 4,
    "道路交叉路口": 3,
    "住宅区": 2,
    "热点商圈": 1,
}
MERGE_MAX_DISTANCE_M = 150.0
STATION_SUFFIXES = ("地铁站", "火车站", "站", "口")


def amap_text(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def normalize_city(value: str | None) -> str | None:
    if not value:
        return None
    city = value.strip()
    if not city:
        return None
    if city.endswith("市") and len(city) > 1:
        return city[:-1]
    return city


def parse_location(value: object) -> tuple[float, float] | None:
    text = amap_text(value)
    if text is None or "," not in text:
        return None
    lng_raw, lat_raw = text.split(",", 1)
    try:
        longitude = float(lng_raw)
        latitude = float(lat_raw)
    except ValueError:
        return None
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        return None
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        return None
    return longitude, latitude


def haversine_m(
    longitude_a: float,
    latitude_a: float,
    longitude_b: float,
    latitude_b: float,
) -> float:
    phi1 = radians(latitude_a)
    phi2 = radians(latitude_b)
    d_phi = radians(latitude_b - latitude_a)
    d_lambda = radians(longitude_b - longitude_a)
    chord = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(min(1.0, sqrt(chord)))


def query_core(address: str, city: str) -> str:
    text = address.strip()
    prefixes = [f"{city}市", city]
    for prefix in sorted(prefixes, key=len, reverse=True):
        if text.startswith(prefix):
            remainder = text[len(prefix) :].strip()
            if len(remainder) >= 2:
                return remainder
    return text


def _match_needles(core: str) -> list[str]:
    needles = [core]
    for suffix in ("地铁站", "火车站", "站"):
        if core.endswith(suffix) and len(core) - len(suffix) >= 2:
            needles.append(core[: -len(suffix)])
            break
    return [item for item in needles if item]


def name_matches(user_address: str, formatted_address: str, city: str) -> bool:
    formatted = formatted_address.strip()
    if not formatted:
        return False
    core = query_core(user_address, city)
    for needle in _match_needles(core):
        if needle in formatted:
            return True
    if len(core) >= 4:
        for size in range(len(core), 3, -1):
            if core[-size:] in formatted:
                return True
    formatted_core = query_core(formatted, city)
    return bool(formatted_core) and formatted_core in user_address


def core_toponym(formatted_address: str) -> str:
    text = re.sub(r"[（(].*?[）)]", "", formatted_address)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"^.*?省", "", text)
    text = re.sub(r"^.*?市", "", text)
    text = re.sub(r"^.*?[区县]", "", text)
    for suffix in STATION_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text


def city_matches(item: dict, request_city: str) -> bool:
    wanted = normalize_city(request_city)
    if wanted is None:
        return False
    city = normalize_city(amap_text(item.get("city")))
    province = normalize_city(amap_text(item.get("province")))
    return city == wanted or province == wanted


def midpoint(longitude_a: float, latitude_a: float, longitude_b: float, latitude_b: float) -> tuple[float, float]:
    return (
        round((longitude_a + longitude_b) / 2, 6),
        round((latitude_a + latitude_b) / 2, 6),
    )
