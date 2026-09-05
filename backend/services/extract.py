from __future__ import annotations

from pathlib import Path
import json
import logging
import re
import time

import httpx
from pydantic import BaseModel, ValidationError

from config import settings
from errors import AppError

logger = logging.getLogger(__name__)

STAGE = "extract"
EXTRACT_TIMEOUT_SECONDS = 20.0
MAX_TOKENS = 800
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "extract.txt"
VAGUE_ADDRESSES = {
    "家",
    "我家",
    "家里",
    "公司",
    "单位",
    "学校",
    "公司楼下",
    "我家附近",
    "附近",
    "这边",
    "那边",
    "这里",
    "那里",
}
CATEGORY_ALIASES = {
    "喝咖啡": "咖啡店",
    "咖啡": "咖啡店",
    "咖啡馆": "咖啡店",
    "来杯咖啡": "咖啡店",
}


class ExtractModelOutput(BaseModel):
    city_a: str | None
    address_a: str | None
    city_b: str | None
    address_b: str | None
    category: str | None
    party_count: int | None
    incomplete_reason: str | None


class ExtractResult(BaseModel):
    city_a: str
    address_a: str
    city_b: str
    address_b: str
    category: str


def _upstream_error(message: str = "地址解析失败，请稍后重试。") -> AppError:
    return AppError(502, "UPSTREAM_ERROR", message, STAGE)


def _model_invalid() -> AppError:
    return AppError(
        502,
        "MODEL_OUTPUT_INVALID",
        "地址解析服务返回格式异常，请稍后重试。",
        STAGE,
    )


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_city(value: str | None) -> str | None:
    city = _blank_to_none(value)
    if city is None:
        return None
    if city.endswith("市") and len(city) > 1:
        return city[:-1]
    return city


def _normalize_address(value: str | None) -> str | None:
    address = _blank_to_none(value)
    if address is None:
        return None
    if address in VAGUE_ADDRESSES:
        return None
    return address


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


def _parse_model_output(raw: str) -> ExtractModelOutput:
    try:
        payload = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError as exc:
        raise _model_invalid() from exc
    try:
        return ExtractModelOutput.model_validate(payload)
    except ValidationError as exc:
        raise _model_invalid() from exc


def _apply_business_rules(parsed: ExtractModelOutput, page_city: str) -> ExtractResult:
    city_a = _normalize_city(parsed.city_a) or _normalize_city(page_city)
    city_b = _normalize_city(parsed.city_b) or _normalize_city(page_city)
    address_a = _normalize_address(parsed.address_a)
    address_b = _normalize_address(parsed.address_b)
    category = _blank_to_none(parsed.category)
    if category is None:
        category = "咖啡店"
    else:
        category = CATEGORY_ALIASES.get(category, category)

    if parsed.party_count is not None and parsed.party_count != 2:
        raise AppError(
            422,
            "PARTY_COUNT_INVALID",
            "目前只支持两个人在同一座城市碰面，请重新说明两个人的位置。",
            STAGE,
        )
    if parsed.party_count is None:
        raise AppError(
            422,
            "EXTRACT_INCOMPLETE",
            "没听清是几个人碰面，请说明两个人的位置。",
            STAGE,
        )
    if address_a is None or address_b is None:
        raise AppError(
            422,
            "EXTRACT_INCOMPLETE",
            "没听清两个人的具体地点，请再说一次各自所在的站名或地址。",
            STAGE,
        )
    if city_a is None or city_b is None:
        raise AppError(
            422,
            "EXTRACT_INCOMPLETE",
            "没听清两个人所在的城市，请重新说明。",
            STAGE,
        )
    if city_a != city_b:
        raise AppError(
            422,
            "CROSS_CITY",
            "目前只支持同一座城市内碰面，请重新说明。",
            STAGE,
        )

    return ExtractResult(
        city_a=city_a,
        address_a=address_a,
        city_b=city_b,
        address_b=address_b,
        category=category,
    )


def _chat_url() -> str:
    return f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"


async def extract_meetup(text: str, page_city: str) -> ExtractResult:
    api_key = settings.deepseek_api_key.strip()
    if not api_key:
        logger.error("extract failed stage=extract reason=missing_api_key")
        raise _upstream_error()

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    user_prompt = (
        f"页面选定城市：{page_city.strip()}\n"
        f"用户口述：{text.strip()}\n"
        "请只输出约定 JSON。"
    )
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    started = time.perf_counter()
    try:
        client = httpx.AsyncClient(timeout=EXTRACT_TIMEOUT_SECONDS)
    except ImportError as exc:
        logger.error("extract failed stage=extract reason=socks_dependency_missing")
        raise _upstream_error() from exc

    try:
        async with client:
            response = await client.post(_chat_url(), headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error("extract timeout stage=extract elapsed_ms=%s", elapsed_ms)
        raise AppError(
            504,
            "UPSTREAM_TIMEOUT",
            "地址解析超时，请稍后重试。",
            STAGE,
        ) from exc
    except httpx.RequestError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error("extract request error stage=extract elapsed_ms=%s", elapsed_ms)
        raise _upstream_error() from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        logger.error(
            "extract upstream error stage=extract http_status=%s elapsed_ms=%s",
            response.status_code,
            elapsed_ms,
        )
        raise _upstream_error()

    try:
        body = response.json()
    except ValueError as exc:
        logger.error("extract invalid json stage=extract elapsed_ms=%s", elapsed_ms)
        raise _model_invalid() from exc

    if not isinstance(body, dict):
        raise _model_invalid()

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise _model_invalid()
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise _model_invalid()
    finish_reason = choices[0].get("finish_reason")
    if finish_reason == "length":
        logger.error("extract truncated stage=extract elapsed_ms=%s", elapsed_ms)
        raise _model_invalid()
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        logger.error("extract empty content stage=extract elapsed_ms=%s", elapsed_ms)
        raise _model_invalid()

    parsed = _parse_model_output(content)
    logger.info(
        "extract model ok stage=extract elapsed_ms=%s text_len=%s party_count=%s",
        elapsed_ms,
        len(text),
        parsed.party_count,
    )
    return _apply_business_rules(parsed, page_city)
