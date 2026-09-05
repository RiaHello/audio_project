from __future__ import annotations

from dataclasses import dataclass
import logging
import math
import time

from errors import AppError
from services.reply import generate_reply
from services.storage import load_stored_search
from services.tts import synthesize_and_store

logger = logging.getLogger(__name__)

STAGE = "finalize"
AUDIO_PUBLIC_BASE = "http://localhost:8003/audio"
TTS_WARNING = "语音合成失败，已为你保留文字推荐。"


@dataclass(frozen=True)
class FinalizeResult:
    reply_text: str
    audio_url: str | None
    warning: str | None


def _first_valid_poi(record: dict) -> dict:
    pois = record.get("pois")
    if not isinstance(pois, list):
        raise AppError(
            404,
            "SEARCH_NOT_FOUND",
            "查询结果不存在或已过期，请重新找店。",
            STAGE,
        )
    for item in pois:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        address = item.get("address")
        distance = item.get("distance_to_midpoint_m")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(address, str) or not address.strip():
            continue
        if not isinstance(distance, (int, float)) or not math.isfinite(float(distance)):
            continue
        category = ""
        query = record.get("query")
        if isinstance(query, dict) and isinstance(query.get("category"), str):
            category = query["category"].strip()
        return {
            "name": name.strip(),
            "address": address.strip(),
            "distance_to_midpoint_m": float(distance),
            "category": category or "咖啡店",
        }
    raise AppError(
        404,
        "SEARCH_NOT_FOUND",
        "查询结果不存在或已过期，请重新找店。",
        STAGE,
    )


async def finalize_meetup(search_id: str) -> FinalizeResult:
    record = load_stored_search(search_id.strip(), stage=STAGE)
    poi = _first_valid_poi(record)
    started = time.perf_counter()
    reply_text = await generate_reply(
        poi["name"],
        poi["address"],
        poi["distance_to_midpoint_m"],
        poi["category"],
    )
    audio_id = await synthesize_and_store(reply_text)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if audio_id is None:
        logger.info(
            "finalize degraded stage=finalize elapsed_ms=%s reply_len=%s",
            elapsed_ms,
            len(reply_text),
        )
        return FinalizeResult(reply_text=reply_text, audio_url=None, warning=TTS_WARNING)
    logger.info(
        "finalize ok stage=finalize elapsed_ms=%s reply_len=%s",
        elapsed_ms,
        len(reply_text),
    )
    return FinalizeResult(
        reply_text=reply_text,
        audio_url=f"{AUDIO_PUBLIC_BASE}/{audio_id}",
        warning=None,
    )
