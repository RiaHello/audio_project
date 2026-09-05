from pathlib import Path
import logging
import tempfile

from fastapi import UploadFile

from errors import AppError
from services.audio_probe import probe_audio_file
from services.storage import save_audio

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 5 * 1024 * 1024
MIN_DURATION_SECONDS = 1.0
MAX_DURATION_SECONDS = 60.0
STAGE = "upload"
READ_CHUNK_SIZE = 1024 * 1024


async def store_uploaded_audio(file: UploadFile) -> str:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(READ_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_AUDIO_BYTES:
            raise AppError(
                413,
                "FILE_TOO_LARGE",
                "录音文件超过 5MB，请缩短录音后重试。",
                STAGE,
            )
        chunks.append(chunk)

    data = b"".join(chunks)
    if not data:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "请上传录音文件。",
            STAGE,
        )

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        probe = probe_audio_file(tmp_path)
        if (
            probe.duration_seconds < MIN_DURATION_SECONDS
            or probe.duration_seconds > MAX_DURATION_SECONDS
        ):
            raise AppError(
                422,
                "AUDIO_DURATION_INVALID",
                "录音时长需在 1 到 60 秒之间，请重新录制。",
                STAGE,
            )
        audio_id = save_audio(tmp_path, probe, size_bytes=total)
        tmp_path = None
        logger.info(
            "upload ok stage=upload audio_id=%s duration_seconds=%.3f size_bytes=%s",
            audio_id,
            probe.duration_seconds,
            total,
        )
        return audio_id
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
