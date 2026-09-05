from __future__ import annotations

import logging
import time

import httpx

from config import settings
from services.audio_format import detect_audio_bytes
from services.storage import save_tts_audio

logger = logging.getLogger(__name__)

TTS_TIMEOUT_SECONDS = 20.0
DOWNLOAD_TIMEOUT_SECONDS = 8.0
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024


def _extract_audio_url(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    if payload.get("code"):
        return None
    output = payload.get("output")
    if not isinstance(output, dict):
        return None
    audio = output.get("audio")
    if not isinstance(audio, dict):
        return None
    url = audio.get("url")
    if not isinstance(url, str):
        return None
    url = url.strip()
    return url or None


async def synthesize_and_store(reply_text: str) -> str | None:
    api_key = settings.bailian_api_key.strip()
    if not api_key:
        logger.error("finalize tts skipped stage=finalize reason=missing_api_key")
        return None

    payload = {
        "model": settings.bailian_tts_model,
        "input": {
            "text": reply_text,
            "voice": settings.bailian_tts_voice,
            "language_type": settings.bailian_tts_language,
        },
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    started = time.perf_counter()
    try:
        client = httpx.AsyncClient(timeout=TTS_TIMEOUT_SECONDS)
    except ImportError:
        logger.error("finalize tts failed stage=finalize reason=socks_dependency_missing")
        return None

    try:
        async with client:
            response = await client.post(
                settings.bailian_tts_url,
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error("finalize tts timeout stage=finalize elapsed_ms=%s", elapsed_ms)
        return None
    except httpx.RequestError:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error("finalize tts request error stage=finalize elapsed_ms=%s", elapsed_ms)
        return None

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        logger.error(
            "finalize tts upstream error stage=finalize http_status=%s elapsed_ms=%s",
            response.status_code,
            elapsed_ms,
        )
        return None
    try:
        body = response.json()
    except ValueError:
        logger.error("finalize tts invalid json stage=finalize elapsed_ms=%s", elapsed_ms)
        return None

    audio_url = _extract_audio_url(body)
    if audio_url is None:
        logger.error("finalize tts missing url stage=finalize elapsed_ms=%s", elapsed_ms)
        return None

    audio_bytes = await _download_audio(audio_url)
    if audio_bytes is None:
        return None
    detected = detect_audio_bytes(audio_bytes)
    if detected is None:
        logger.error("finalize tts unknown audio format stage=finalize size_bytes=%s", len(audio_bytes))
        return None
    try:
        audio_id = save_tts_audio(
            audio_bytes,
            extension=detected.extension,
            content_type=detected.content_type,
            container=detected.container,
        )
    except OSError:
        logger.error("finalize tts save failed stage=finalize")
        return None
    logger.info(
        "finalize tts ok stage=finalize elapsed_ms=%s audio_format=%s size_bytes=%s",
        elapsed_ms,
        detected.container,
        len(audio_bytes),
    )
    return audio_id


async def _download_audio(audio_url: str) -> bytes | None:
    started = time.perf_counter()
    try:
        client = httpx.AsyncClient(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True)
    except ImportError:
        logger.error("finalize tts download failed stage=finalize reason=socks_dependency_missing")
        return None
    try:
        async with client:
            response = await client.get(audio_url)
    except httpx.TimeoutException:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error("finalize tts download timeout stage=finalize elapsed_ms=%s", elapsed_ms)
        return None
    except httpx.RequestError:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        logger.error("finalize tts download error stage=finalize elapsed_ms=%s", elapsed_ms)
        return None
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code >= 400:
        logger.error(
            "finalize tts download http_status=%s elapsed_ms=%s",
            response.status_code,
            elapsed_ms,
        )
        return None
    data = response.content
    if not data or len(data) > MAX_DOWNLOAD_BYTES:
        logger.error(
            "finalize tts download size invalid stage=finalize size_bytes=%s elapsed_ms=%s",
            len(data) if data else 0,
            elapsed_ms,
        )
        return None
    return data
