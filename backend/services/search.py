from __future__ import annotations

from dataclasses import dataclass
import asyncio
import logging
import math
import time

from errors import AppError
from services.amap import geocode, search_around
from services.geo import (
    LEVEL_RANK,
    LEVEL_WHITELIST,
    MERGE_MAX_DISTANCE_M,
    amap_text,
    city_matches,
    core_toponym,
    haversine_m,
    midpoint,
    name_matches,
    normalize_city,
    parse_location,
)
from services.storage import save_search_result

logger = logging.getLogger(__name__)

STAGE = "search"
SEARCH_TOTAL_TIMEOUT_SECONDS = 20.0
RADIUS_FIRST_M = 2000
RADIUS_EXPAND_M = 5000
MAX_POIS = 3


@dataclass(frozen=True)
class ResolvedPoint:
    longitude: float
    latitude: float
    formatted_address: str
    level: str


@dataclass(frozen=True)
class PoiCandidate:
    name: str
    address: str
    longitude: float
    latitude: float
    distance_to_midpoint_m: float


@dataclass(frozen=True)
class SearchResult:
    search_id: str
    longitude: float
    latitude: float
    pois: list[PoiCandidate]


def _unresolved() -> AppError:
    return AppError(
        422,
        "GEO_UNRESOLVED",
        "地点无法定位，请说更具体的站名或地址。",
        STAGE,
    )


def _ambiguous() -> AppError:
    return AppError(
        422,
        "GEO_AMBIGUOUS",
        "找到多个可能的地点，请补充更具体的站名、出入口或地址。",
        STAGE,
    )


def _no_poi() -> AppError:
    return AppError(
        422,
        "NO_POI",
        "中点附近没有找到合适的店，请换一个更具体的地点或类别再试。",
        STAGE,
    )


def _parse_amap_distance(raw: object) -> float | None:
    text = amap_text(raw)
    if text is None:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value < 0 or not math.isfinite(value):
        return None
    return value


def _dedupe_geocodes(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for item in items:
        key = "".join((item["formatted_address"] or "").split())
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _pick_merged(items: list[dict]) -> dict:
    return max(items, key=lambda item: (LEVEL_RANK.get(item["level"], 0), -items.index(item)))


def resolve_geocode_point(payload: dict, address: str, city: str) -> ResolvedPoint:
    raw = payload.get("geocodes")
    if not isinstance(raw, list):
        raw = []

    filtered: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        location = parse_location(item.get("location"))
        if location is None:
            continue
        if not city_matches(item, city):
            continue
        level = amap_text(item.get("level"))
        if level not in LEVEL_WHITELIST:
            continue
        formatted = amap_text(item.get("formatted_address"))
        if formatted is None:
            continue
        if not name_matches(address, formatted, city):
            continue
        filtered.append(
            {
                "longitude": location[0],
                "latitude": location[1],
                "formatted_address": formatted,
                "level": level,
            }
        )

    filtered = _dedupe_geocodes(filtered)
    if not filtered:
        raise _unresolved()
    if len(filtered) == 1:
        chosen = filtered[0]
        return ResolvedPoint(
            longitude=chosen["longitude"],
            latitude=chosen["latitude"],
            formatted_address=chosen["formatted_address"],
            level=chosen["level"],
        )

    names = {core_toponym(item["formatted_address"]) for item in filtered}
    pairwise: list[float] = []
    for index, left in enumerate(filtered):
        for right in filtered[index + 1 :]:
            pairwise.append(
                haversine_m(
                    left["longitude"],
                    left["latitude"],
                    right["longitude"],
                    right["latitude"],
                )
            )
    max_distance = max(pairwise) if pairwise else 0.0
    if len(names) == 1 and max_distance <= MERGE_MAX_DISTANCE_M:
        chosen = _pick_merged(filtered)
        return ResolvedPoint(
            longitude=chosen["longitude"],
            latitude=chosen["latitude"],
            formatted_address=chosen["formatted_address"],
            level=chosen["level"],
        )
    raise _ambiguous()


def parse_around_pois(
    payload: dict,
    city: str,
    mid_lng: float,
    mid_lat: float,
) -> list[PoiCandidate]:
    raw = payload.get("pois")
    if not isinstance(raw, list):
        return []

    candidates: list[PoiCandidate] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = amap_text(item.get("name"))
        address = amap_text(item.get("address"))
        location = parse_location(item.get("location"))
        if name is None or address is None or location is None:
            continue
        poi_city = amap_text(item.get("cityname"))
        if poi_city is not None and normalize_city(poi_city) != normalize_city(city):
            continue
        distance = _parse_amap_distance(item.get("distance"))
        if distance is None:
            distance = haversine_m(location[0], location[1], mid_lng, mid_lat)
        candidates.append(
            PoiCandidate(
                name=name,
                address=address,
                longitude=location[0],
                latitude=location[1],
                distance_to_midpoint_m=float(round(distance)),
            )
        )
    candidates.sort(key=lambda item: item.distance_to_midpoint_m)
    return candidates[:MAX_POIS]


async def _collect_pois(
    city: str,
    category: str,
    mid_lng: float,
    mid_lat: float,
) -> tuple[list[PoiCandidate], int]:
    first = await search_around(mid_lng, mid_lat, category, city, RADIUS_FIRST_M)
    pois = parse_around_pois(first, city, mid_lng, mid_lat)
    if pois:
        return pois, RADIUS_FIRST_M
    expanded = await search_around(mid_lng, mid_lat, category, city, RADIUS_EXPAND_M)
    pois = parse_around_pois(expanded, city, mid_lng, mid_lat)
    if pois:
        return pois, RADIUS_EXPAND_M
    raise _no_poi()


async def _search_meetup(
    city_a: str,
    address_a: str,
    city_b: str,
    address_b: str,
    category: str,
) -> SearchResult:
    normalized_a = normalize_city(city_a)
    normalized_b = normalize_city(city_b)
    if normalized_a is None or normalized_b is None:
        raise _unresolved()
    if normalized_a != normalized_b:
        raise AppError(
            422,
            "CROSS_CITY",
            "目前只支持同一座城市内碰面，请重新说明。",
            STAGE,
        )

    started = time.perf_counter()
    payload_a = await geocode(address_a.strip(), normalized_a)
    point_a = resolve_geocode_point(payload_a, address_a.strip(), normalized_a)
    payload_b = await geocode(address_b.strip(), normalized_b)
    point_b = resolve_geocode_point(payload_b, address_b.strip(), normalized_b)

    mid_lng, mid_lat = midpoint(
        point_a.longitude,
        point_a.latitude,
        point_b.longitude,
        point_b.latitude,
    )
    pois, radius_m = await _collect_pois(normalized_a, category.strip(), mid_lng, mid_lat)
    search_id = save_search_result(
        {
            "query": {
                "city_a": normalized_a,
                "address_a": address_a.strip(),
                "city_b": normalized_b,
                "address_b": address_b.strip(),
                "category": category.strip(),
            },
            "point_a": {
                "longitude": point_a.longitude,
                "latitude": point_a.latitude,
                "formatted_address": point_a.formatted_address,
                "level": point_a.level,
            },
            "point_b": {
                "longitude": point_b.longitude,
                "latitude": point_b.latitude,
                "formatted_address": point_b.formatted_address,
                "level": point_b.level,
            },
            "midpoint": {"longitude": mid_lng, "latitude": mid_lat},
            "radius_m": radius_m,
            "pois": [
                {
                    "name": poi.name,
                    "address": poi.address,
                    "longitude": poi.longitude,
                    "latitude": poi.latitude,
                    "distance_to_midpoint_m": poi.distance_to_midpoint_m,
                }
                for poi in pois
            ],
        }
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "search ok stage=search elapsed_ms=%s search_id=%s poi_count=%s radius_m=%s",
        elapsed_ms,
        search_id,
        len(pois),
        radius_m,
    )
    return SearchResult(
        search_id=search_id,
        longitude=mid_lng,
        latitude=mid_lat,
        pois=pois,
    )


async def search_meetup(
    city_a: str,
    address_a: str,
    city_b: str,
    address_b: str,
    category: str,
) -> SearchResult:
    try:
        return await asyncio.wait_for(
            _search_meetup(city_a, address_a, city_b, address_b, category),
            timeout=SEARCH_TOTAL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        logger.error("search timeout stage=search reason=total_budget")
        raise AppError(
            504,
            "UPSTREAM_TIMEOUT",
            "地点查询超时，请稍后重试。",
            STAGE,
        ) from exc
