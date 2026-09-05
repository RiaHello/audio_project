from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

ASR_OK_BODY = {
    "output": {
        "choices": [
            {
                "message": {
                    "content": [{"text": "我在杭州东站，朋友在西湖龙翔桥地铁站。"}]
                }
            }
        ]
    }
}


def _write_audio(tmp_path: Path, audio_id: str, created_at: datetime | None = None) -> None:
    folder = tmp_path / audio_id
    folder.mkdir(parents=True)
    (folder / "recording.webm").write_bytes(b"fake-webm-bytes")
    created = created_at or datetime.now(timezone.utc)
    meta = {
        "audio_id": audio_id,
        "created_at": created.isoformat(),
        "stored_name": "recording.webm",
        "container": "matroska,webm",
        "codec": "opus",
        "duration_seconds": 3.0,
        "size_bytes": 15,
    }
    (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


class _DummyResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _DummyClient:
    def __init__(self, response: _DummyResponse | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.posted_json = None

    async def __aenter__(self) -> "_DummyClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url, headers=None, json=None):
        self.posted_json = json
        if self._error:
            raise self._error
        assert self._response is not None
        return self._response


def test_asr_success_mock(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_AUDIO_DIR", tmp_path)
    monkeypatch.setattr("services.asr.settings.bailian_api_key", "sk-test")
    audio_id = "11111111-1111-1111-1111-111111111111"
    _write_audio(tmp_path, audio_id)
    dummy = _DummyClient(response=_DummyResponse(200, ASR_OK_BODY))
    monkeypatch.setattr("services.asr.httpx.AsyncClient", lambda timeout: dummy)

    response = client.post("/asr", json={"audio_id": audio_id})
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["text"] == "我在杭州东站，朋友在西湖龙翔桥地铁站。"
    audio_field = dummy.posted_json["input"]["messages"][0]["content"][0]["audio"]
    assert audio_field.startswith("data:audio/webm;base64,")


def test_asr_not_found(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_AUDIO_DIR", tmp_path)
    response = client.post(
        "/asr",
        json={"audio_id": "22222222-2222-2222-2222-222222222222"},
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "AUDIO_NOT_FOUND"
    assert body["error"]["stage"] == "asr"


def test_asr_expired(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_AUDIO_DIR", tmp_path)
    audio_id = "33333333-3333-3333-3333-333333333333"
    _write_audio(
        tmp_path,
        audio_id,
        created_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    response = client.post("/asr", json={"audio_id": audio_id})
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "AUDIO_NOT_FOUND"


def test_asr_empty_text(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_AUDIO_DIR", tmp_path)
    monkeypatch.setattr("services.asr.settings.bailian_api_key", "sk-test")
    audio_id = "44444444-4444-4444-4444-444444444444"
    _write_audio(tmp_path, audio_id)
    empty_body = {
        "output": {"choices": [{"message": {"content": [{"text": "   "}]}}]}
    }
    dummy = _DummyClient(response=_DummyResponse(200, empty_body))
    monkeypatch.setattr("services.asr.httpx.AsyncClient", lambda timeout: dummy)
    response = client.post("/asr", json={"audio_id": audio_id})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "ASR_EMPTY"
    assert body["error"]["stage"] == "asr"


def test_asr_timeout(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_AUDIO_DIR", tmp_path)
    monkeypatch.setattr("services.asr.settings.bailian_api_key", "sk-test")
    audio_id = "55555555-5555-5555-5555-555555555555"
    _write_audio(tmp_path, audio_id)
    dummy = _DummyClient(error=httpx.TimeoutException("timed out"))
    monkeypatch.setattr("services.asr.httpx.AsyncClient", lambda timeout: dummy)
    response = client.post("/asr", json={"audio_id": audio_id})
    assert response.status_code == 504
    body = response.json()
    assert body["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert body["error"]["stage"] == "asr"


def test_asr_upstream_error(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_AUDIO_DIR", tmp_path)
    monkeypatch.setattr("services.asr.settings.bailian_api_key", "sk-test")
    audio_id = "66666666-6666-6666-6666-666666666666"
    _write_audio(tmp_path, audio_id)
    dummy = _DummyClient(response=_DummyResponse(500, {"message": "fail"}))
    monkeypatch.setattr("services.asr.httpx.AsyncClient", lambda timeout: dummy)
    response = client.post("/asr", json={"audio_id": audio_id})
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "UPSTREAM_ERROR"


def test_asr_invalid_output(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_AUDIO_DIR", tmp_path)
    monkeypatch.setattr("services.asr.settings.bailian_api_key", "sk-test")
    audio_id = "77777777-7777-7777-7777-777777777777"
    _write_audio(tmp_path, audio_id)
    dummy = _DummyClient(response=_DummyResponse(200, {"output": {}}))
    monkeypatch.setattr("services.asr.httpx.AsyncClient", lambda timeout: dummy)
    response = client.post("/asr", json={"audio_id": audio_id})
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "MODEL_OUTPUT_INVALID"


def test_asr_missing_field(client: TestClient) -> None:
    response = client.post("/asr", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["stage"] == "asr"
