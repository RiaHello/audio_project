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

STAGE = "finalize"
REPLY_TIMEOUT_SECONDS = 15.0
MAX_TOKENS = 400
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "reply.txt"


class ReplyModelOutput(BaseModel):
    reply_text: str


def _upstream_error(message: str = "推荐语生成失败，请稍后重试。") -> AppError:
    return AppError(502, "UPSTREAM_ERROR", message, STAGE)


def _model_invalid() -> AppError:
    return AppError(
        502,
        "MODEL_OUTPUT_INVALID",
        "推荐语生成失败，请稍后重试。",
        STAGE,
    )


def _chat_url() -> str:
    return f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"


def _strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text, count=1)
    return text.strip()


def _parse_reply(raw: str, shop_name: str, shop_address: str) -> str:
    try:
        payload = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError as exc:
        raise _model_invalid() from exc
    try:
        parsed = ReplyModelOutput.model_validate(payload)
    except ValidationError as exc:
        raise _model_invalid() from exc
    reply_text = parsed.reply_text.strip()
    if not reply_text:
        raise _model_invalid()
    if shop_name not in reply_text or shop_address not in reply_text:
        logger.error("finalize reply mutated shop fields stage=finalize")
        raise _model_invalid()
    return reply_text


async def generate_reply(
    shop_name: str,
    shop_address: str,
    distance_m: float,
    category: str,
) -> str:
    api_key = settings.deepseek_api_key.strip()
    if not api_key:
        logger.error("finalize failed stage=finalize reason=missing_api_key")
        raise _upstream_error()

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    user_prompt = (
        f"店名={shop_name}\n"
        f"地址={shop_address}\n"
        f"距离中点={int(round(distance_m))}米\n"
        f"类别={category}\n"
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
        client = httpx.AsyncClient(timeout=REPLY_TIMEOUT_SECONDS)
    except ImportError as exc:
        logger.error("finalize failed stage=finalize reason=socks_dependency_missing")
        raise _upstream_error() from exc

    try:
        async with client:
            response = await client.post(_chat_url(), headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error("finalize reply timeout stage=finalize elapsed_ms=%s", elapsed_ms)
        raise AppError(
            504,
            "UPSTREAM_TIMEOUT",
            "推荐语生成超时，请稍后重试。",
            STAGE,
        ) from exc
    except httpx.RequestError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error("finalize reply request error stage=finalize elapsed_ms=%s", elapsed_ms)
        raise _upstream_error() from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        logger.error(
            "finalize reply upstream error stage=finalize http_status=%s elapsed_ms=%s",
            response.status_code,
            elapsed_ms,
        )
        raise _upstream_error()

    try:
        body = response.json()
    except ValueError as exc:
        logger.error("finalize reply invalid json stage=finalize elapsed_ms=%s", elapsed_ms)
        raise _model_invalid() from exc

    if not isinstance(body, dict):
        raise _model_invalid()
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise _model_invalid()
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise _model_invalid()
    if choices[0].get("finish_reason") == "length":
        logger.error("finalize reply truncated stage=finalize elapsed_ms=%s", elapsed_ms)
        raise _model_invalid()
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        logger.error("finalize reply empty content stage=finalize elapsed_ms=%s", elapsed_ms)
        raise _model_invalid()

    reply_text = _parse_reply(content, shop_name, shop_address)
    logger.info(
        "finalize reply ok stage=finalize elapsed_ms=%s reply_len=%s",
        elapsed_ms,
        len(reply_text),
    )
    return reply_text
