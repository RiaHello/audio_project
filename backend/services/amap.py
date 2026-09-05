from __future__ import annotations

import logging
import time

import httpx

from config import settings
from errors import AppError

logger = logging.getLogger(__name__)

STAGE = "search"
GEOCODE_URL = "https://restapi.amap.com/v3/geocode/geo"
AROUND_URL = "https://restapi.amap.com/v3/place/around"
GEOCODE_TIMEOUT_SECONDS = 4.0
AROUND_TIMEOUT_SECONDS = 4.0


def _upstream() -> AppError:
    return AppError(502, "UPSTREAM_ERROR", "地点查询失败，请稍后重试。", STAGE)


def _timeout() -> AppError:
    return AppError(504, "UPSTREAM_TIMEOUT", "地点查询超时，请稍后重试。", STAGE)


async def _amap_get(url: str, params: dict, timeout: float) -> dict:
    api_key = settings.amap_api_key.strip()
    if not api_key:
        logger.error("search failed stage=search reason=missing_api_key")
        raise _upstream()
    query = {**params, "key": api_key, "output": "JSON"}
    started = time.perf_counter()
    try:
        client = httpx.AsyncClient(timeout=timeout)
    except ImportError as exc:
        logger.error("search failed stage=search reason=socks_dependency_missing")
        raise _upstream() from exc
    try:
        async with client:
            response = await client.get(url, params=query)
    except httpx.TimeoutException as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error("search timeout stage=search elapsed_ms=%s", elapsed_ms)
        raise _timeout() from exc
    except httpx.RequestError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error("search request error stage=search elapsed_ms=%s", elapsed_ms)
        raise _upstream() from exc
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        logger.error(
            "search upstream http_status=%s elapsed_ms=%s",
            response.status_code,
            elapsed_ms,
        )
        raise _upstream()
    try:
        payload = response.json()
    except ValueError as exc:
        logger.error("search invalid json stage=search elapsed_ms=%s", elapsed_ms)
        raise _upstream() from exc
    if not isinstance(payload, dict):
        raise _upstream()
    infocode = str(payload.get("infocode") or "")
    status = str(payload.get("status") or "")
    if status != "1" or infocode != "10000":
        logger.error(
            "search amap business status=%s infocode=%s elapsed_ms=%s",
            status,
            infocode,
            elapsed_ms,
        )
        raise _upstream()
    return payload


async def geocode(address: str, city: str) -> dict:
    return await _amap_get(
        GEOCODE_URL,
        {"address": address, "city": city},
        GEOCODE_TIMEOUT_SECONDS,
    )


async def search_around(
    longitude: float,
    latitude: float,
    keywords: str,
    city: str,
    radius_m: int,
) -> dict:
    location = f"{longitude:.6f},{latitude:.6f}"
    return await _amap_get(
        AROUND_URL,
        {
            "location": location,
            "keywords": keywords,
            "city": city,
            "radius": str(radius_m),
            "offset": "20",
            "page": "1",
            "extensions": "base",
        },
        AROUND_TIMEOUT_SECONDS,
    )
