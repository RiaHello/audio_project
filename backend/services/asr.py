from __future__ import annotations

import base64
import logging
import time

import httpx

from config import settings
from errors import AppError
from services.storage import load_stored_audio

logger = logging.getLogger(__name__)

STAGE = "asr"
ASR_TIMEOUT_SECONDS = 20.0
MAX_ASR_BASE64_BYTES = 10 * 1024 * 1024
AUDIO_DATA_MIME = "audio/webm"


def _extract_text(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    output = payload.get("output")
    if not isinstance(output, dict):
        return None
    choices = output.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return None
    message = first_choice.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list) or not content:
        return None
    first_part = content[0]
    if isinstance(first_part, str):
        return first_part.strip()
    if not isinstance(first_part, dict):
        return None
    text = first_part.get("text")
    if not isinstance(text, str):
        return None
    return text.strip()


def _upstream_error(message: str = "语音识别失败，请稍后重试。") -> AppError:
    return AppError(502, "UPSTREAM_ERROR", message, STAGE)


async def transcribe_audio(audio_id: str) -> str:
    audio_path, _meta = load_stored_audio(audio_id, stage=STAGE)
    audio_bytes = audio_path.read_bytes()
    encoded = base64.b64encode(audio_bytes).decode("ascii")
    if len(encoded.encode("ascii")) > MAX_ASR_BASE64_BYTES:
        raise AppError(
            413,
            "FILE_TOO_LARGE",
            "录音编码后超过识别限制，请缩短录音后重试。",
            STAGE,
        )

    api_key = settings.bailian_api_key.strip()
    if not api_key:
        logger.error("asr failed stage=asr reason=missing_api_key")
        raise _upstream_error()

    data_url = f"data:{AUDIO_DATA_MIME};base64,{encoded}"
    payload = {
        "model": settings.bailian_asr_model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"audio": data_url}],
                }
            ]
        },
        "parameters": {
            "asr_options": {
                "enable_itn": False,
                "language": "zh",
            }
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    started = time.perf_counter()
    try:
        client = httpx.AsyncClient(timeout=ASR_TIMEOUT_SECONDS)
    except ImportError as exc:
        logger.error("asr failed stage=asr reason=socks_dependency_missing")
        raise _upstream_error() from exc

    try:
        async with client:
            response = await client.post(
                settings.bailian_asr_url,
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error("asr timeout stage=asr elapsed_ms=%s", elapsed_ms)
        raise AppError(
            504,
            "UPSTREAM_TIMEOUT",
            "语音识别超时，请稍后重试。",
            STAGE,
        ) from exc
    except httpx.RequestError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error("asr request error stage=asr elapsed_ms=%s", elapsed_ms)
        raise _upstream_error() from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        logger.error(
            "asr upstream error stage=asr http_status=%s elapsed_ms=%s",
            response.status_code,
            elapsed_ms,
        )
        raise _upstream_error()

    try:
        body = response.json()
    except ValueError as exc:
        logger.error("asr invalid json stage=asr elapsed_ms=%s", elapsed_ms)
        raise AppError(
            502,
            "MODEL_OUTPUT_INVALID",
            "语音识别服务返回格式异常，请稍后重试。",
            STAGE,
        ) from exc

    if isinstance(body, dict) and body.get("code"):
        logger.error("asr business error stage=asr elapsed_ms=%s", elapsed_ms)
        raise _upstream_error()

    text = _extract_text(body)
    if text is None:
        logger.error("asr output invalid stage=asr elapsed_ms=%s", elapsed_ms)
        raise AppError(
            502,
            "MODEL_OUTPUT_INVALID",
            "语音识别服务返回格式异常，请稍后重试。",
            STAGE,
        )
    if text == "":
        logger.info("asr empty stage=asr elapsed_ms=%s text_len=0", elapsed_ms)
        raise AppError(
            422,
            "ASR_EMPTY",
            "没有听清内容，请重新说一次。",
            STAGE,
        )

    logger.info("asr ok stage=asr elapsed_ms=%s text_len=%s", elapsed_ms, len(text))
    return text
