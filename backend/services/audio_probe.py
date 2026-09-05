from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import math
import shutil
import subprocess

from errors import AppError

PROBE_TIMEOUT_SECONDS = 5.0
STAGE = "upload"


@dataclass(frozen=True)
class AudioProbe:
    container: str
    codec: str
    duration_seconds: float


def _parse_duration(value: object) -> float | None:
    if value is None or value == "" or value == "N/A":
        return None
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(duration) or duration <= 0:
        return None
    return duration


def _run_ffprobe(path: Path, extra_args: list[str]) -> dict:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise AppError(
            500,
            "INTERNAL_ERROR",
            "服务器缺少音频校验工具 ffprobe，请安装 FFmpeg 后重试。",
            STAGE,
        )
    command = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        *extra_args,
        str(path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppError(
            422,
            "AUDIO_DURATION_INVALID",
            "无法读取录音时长，请重新录制。",
            STAGE,
        ) from exc

    if completed.returncode != 0:
        raise AppError(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "仅支持 WebM/Opus 录音，请更换浏览器后重试。",
            STAGE,
        )
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise AppError(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "仅支持 WebM/Opus 录音，请更换浏览器后重试。",
            STAGE,
        ) from exc
    if not isinstance(payload, dict):
        raise AppError(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "仅支持 WebM/Opus 录音，请更换浏览器后重试。",
            STAGE,
        )
    return payload


def _duration_from_packets(path: Path) -> float | None:
    try:
        payload = _run_ffprobe(
            path,
            [
                "-select_streams",
                "a:0",
                "-show_packets",
                "-show_entries",
                "packet=pts_time,duration_time",
            ],
        )
    except AppError:
        return None
    packets = payload.get("packets") or []
    if not packets:
        return None
    last = packets[-1]
    pts = _parse_duration(last.get("pts_time")) or 0.0
    packet_duration = _parse_duration(last.get("duration_time")) or 0.0
    total = pts + packet_duration
    if total <= 0:
        return None
    return total


def probe_audio_file(path: Path) -> AudioProbe:
    payload = _run_ffprobe(path, ["-show_format", "-show_streams"])
    format_info = payload.get("format") or {}
    format_name = str(format_info.get("format_name") or "").lower()
    streams = payload.get("streams") or []
    audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
    if not audio_streams:
        raise AppError(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "仅支持 WebM/Opus 录音，请更换浏览器后重试。",
            STAGE,
        )

    codec = str(audio_streams[0].get("codec_name") or "").lower()
    container_ok = "webm" in format_name or "matroska" in format_name
    if not container_ok or codec != "opus":
        raise AppError(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "仅支持 WebM/Opus 录音，请更换浏览器后重试。",
            STAGE,
        )

    duration = _parse_duration(format_info.get("duration")) or _parse_duration(
        audio_streams[0].get("duration")
    )
    if duration is None:
        duration = _duration_from_packets(path)
    if duration is None:
        raise AppError(
            422,
            "AUDIO_DURATION_INVALID",
            "无法读取录音时长，请重新录制。",
            STAGE,
        )

    return AudioProbe(container=format_name, codec=codec, duration_seconds=duration)
