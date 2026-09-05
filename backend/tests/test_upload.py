from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from errors import AppError
from services.audio_probe import AudioProbe
from services.upload_audio import MAX_AUDIO_BYTES


def test_upload_success(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_AUDIO_DIR", tmp_path)

    def fake_probe(_path: Path) -> AudioProbe:
        return AudioProbe(container="matroska,webm", codec="opus", duration_seconds=3.2)

    monkeypatch.setattr("services.upload_audio.probe_audio_file", fake_probe)

    response = client.post(
        "/upload",
        files={"file": ("clip.webm", BytesIO(b"fake-webm-bytes"), "audio/webm")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["request_id"]
    audio_id = body["data"]["audio_id"]
    assert audio_id
    assert "/" not in audio_id
    assert "\\" not in audio_id
    saved = tmp_path / audio_id
    assert (saved / "recording.webm").is_file()
    assert (saved / "meta.json").is_file()
    meta = (saved / "meta.json").read_text(encoding="utf-8")
    assert "created_at" in meta
    assert audio_id in meta


def test_upload_too_large(client: TestClient) -> None:
    payload = b"0" * (MAX_AUDIO_BYTES + 1)
    response = client.post(
        "/upload",
        files={"file": ("huge.webm", BytesIO(payload), "audio/webm")},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "FILE_TOO_LARGE"
    assert body["error"]["stage"] == "upload"
    assert body["error"]["message"]


def test_upload_unsupported_format(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_AUDIO_DIR", tmp_path)

    def fake_probe(_path: Path) -> AudioProbe:
        raise AppError(
            415,
            "UNSUPPORTED_MEDIA_TYPE",
            "仅支持 WebM/Opus 录音，请更换浏览器后重试。",
            "upload",
        )

    monkeypatch.setattr("services.upload_audio.probe_audio_file", fake_probe)
    response = client.post(
        "/upload",
        files={"file": ("clip.mp3", BytesIO(b"not-webm"), "audio/mpeg")},
    )
    assert response.status_code == 415
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert body["error"]["stage"] == "upload"


def test_upload_duration_invalid(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_AUDIO_DIR", tmp_path)

    def fake_probe(_path: Path) -> AudioProbe:
        return AudioProbe(container="matroska,webm", codec="opus", duration_seconds=0.4)

    monkeypatch.setattr("services.upload_audio.probe_audio_file", fake_probe)
    response = client.post(
        "/upload",
        files={"file": ("clip.webm", BytesIO(b"fake-webm-bytes"), "audio/webm")},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "AUDIO_DURATION_INVALID"
    assert body["error"]["stage"] == "upload"


def test_upload_missing_file(client: TestClient) -> None:
    response = client.post("/upload")
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["stage"] == "upload"
