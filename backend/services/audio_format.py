from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectedAudio:
    extension: str
    content_type: str
    container: str


def detect_audio_bytes(data: bytes) -> DetectedAudio | None:
    if len(data) < 12:
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return DetectedAudio("wav", "audio/wav", "wav")
    if data[:4] == b"OggS":
        return DetectedAudio("ogg", "audio/ogg", "ogg")
    if data[:4] == b"fLaC":
        return DetectedAudio("flac", "audio/flac", "flac")
    if data[:3] == b"ID3":
        return DetectedAudio("mp3", "audio/mpeg", "mp3")
    if data[0] == 0xFF and data[1] & 0xE0 == 0xE0:
        return DetectedAudio("mp3", "audio/mpeg", "mp3")
    return None
