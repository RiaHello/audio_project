from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import shutil
import uuid

from config import settings
from errors import AppError
from services.audio_probe import AudioProbe

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIO_DIR = BACKEND_ROOT / "storage" / "audio"


def audio_dir() -> Path:
    path = DEFAULT_AUDIO_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_audio(
    source: Path,
    probe: AudioProbe,
    size_bytes: int,
) -> str:
    audio_id = str(uuid.uuid4())
    dest_dir = audio_dir() / audio_id
    dest_dir.mkdir(parents=True, exist_ok=False)
    dest_file = dest_dir / "recording.webm"
    shutil.move(str(source), dest_file)
    meta = {
        "audio_id": audio_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stored_name": dest_file.name,
        "container": probe.container,
        "codec": probe.codec,
        "duration_seconds": probe.duration_seconds,
        "size_bytes": size_bytes,
    }
    (dest_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return audio_id


def _parse_created_at(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        created = datetime.fromisoformat(value)
    except ValueError:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return created


def load_stored_audio(audio_id: str, *, stage: str) -> tuple[Path, dict]:
    not_found = AppError(
        404,
        "AUDIO_NOT_FOUND",
        "录音不存在或已过期，请重新录音。",
        stage,
    )
    try:
        uuid.UUID(audio_id)
    except ValueError as exc:
        raise not_found from exc

    dest_dir = audio_dir() / audio_id
    meta_path = dest_dir / "meta.json"
    if not meta_path.is_file():
        raise not_found

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise not_found from exc
    if not isinstance(meta, dict):
        raise not_found

    stored_name = meta.get("stored_name") or "recording.webm"
    if not isinstance(stored_name, str) or "/" in stored_name or "\\" in stored_name:
        raise not_found
    audio_path = dest_dir / stored_name
    if not audio_path.is_file():
        raise not_found

    created = _parse_created_at(meta.get("created_at"))
    if created is None:
        raise not_found
    expires_at = created + timedelta(hours=settings.audio_ttl_hours)
    if datetime.now(timezone.utc) >= expires_at:
        raise not_found

    return audio_path, meta
