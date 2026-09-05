from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import uuid

import httpx
from fastapi.testclient import TestClient

from services.audio_format import detect_audio_bytes
from services.reply import REPLY_TIMEOUT_SECONDS
from services.tts import DOWNLOAD_TIMEOUT_SECONDS, TTS_TIMEOUT_SECONDS

SHOP_NAME = "某咖啡店湖滨店"
SHOP_ADDRESS = "杭州市上城区湖滨路1号"
REPLY_TEXT = (
    f"推荐你们在中点附近的{SHOP_NAME}碰面，地址是{SHOP_ADDRESS}，距离中点约三百二十米。"
)
WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVE" + b"\x00" * 36
MP3_BYTES = b"ID3" + b"\x00" * 24


class _DummyResponse:
    def __init__(self, status_code: int, payload: object = None, content: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _DummyClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict | None]] = []
        self.gets: list[str] = []
        self.deepseek: _DummyResponse | None = None
        self.deepseek_error: Exception | None = None
        self.tts: _DummyResponse | None = None
        self.tts_error: Exception | None = None
        self.download: _DummyResponse | None = None
        self.download_error: Exception | None = None

    async def __aenter__(self) -> "_DummyClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url, headers=None, json=None):
        self.posts.append((url, json))
        if "chat/completions" in url:
            if self.deepseek_error:
                raise self.deepseek_error
            assert self.deepseek is not None
            return self.deepseek
        if self.tts_error:
            raise self.tts_error
        assert self.tts is not None
        return self.tts

    async def get(self, url, **kwargs):
        self.gets.append(url)
        if self.download_error:
            raise self.download_error
        assert self.download is not None
        return self.download


def _deepseek_body(content: object) -> dict:
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": content},
            }
        ]
    }


def _tts_body(url: str) -> dict:
    return {"output": {"audio": {"url": url, "data": ""}}}


def _write_search(tmp_path: Path, search_id: str, **overrides) -> None:
    folder = tmp_path / search_id
    folder.mkdir(parents=True)
    record = {
        "search_id": search_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "query": {
            "city_a": "杭州",
            "address_a": "杭州东站",
            "city_b": "杭州",
            "address_b": "西湖龙翔桥地铁站",
            "category": "咖啡店",
        },
        "pois": [
            {
                "name": SHOP_NAME,
                "address": SHOP_ADDRESS,
                "distance_to_midpoint_m": 320,
            },
            {
                "name": "另一家不该出现的店",
                "address": "杭州市上城区延安路88号",
                "distance_to_midpoint_m": 540,
            },
        ],
    }
    record.update(overrides)
    (folder / "result.json").write_text(
        json.dumps(record, ensure_ascii=False),
        encoding="utf-8",
    )


def _patch(
    monkeypatch,
    dummy: _DummyClient,
    search_dir: Path,
    audio_dir: Path,
    *,
    tts_key: bool = True,
) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_SEARCH_DIR", search_dir)
    monkeypatch.setattr("services.storage.DEFAULT_AUDIO_DIR", audio_dir)
    monkeypatch.setattr("services.reply.settings.deepseek_api_key", "sk-test")
    monkeypatch.setattr(
        "services.tts.settings.bailian_api_key",
        "sk-test" if tts_key else "",
    )
    monkeypatch.setattr(
        "services.reply.httpx.AsyncClient",
        lambda *args, **kwargs: dummy,
    )
    monkeypatch.setattr(
        "services.tts.httpx.AsyncClient",
        lambda *args, **kwargs: dummy,
    )


def test_timeout_budget() -> None:
    assert REPLY_TIMEOUT_SECONDS == 15.0
    assert TTS_TIMEOUT_SECONDS == 20.0
    assert DOWNLOAD_TIMEOUT_SECONDS == 8.0


def test_detect_wav_from_bytes_not_suffix() -> None:
    assert detect_audio_bytes(WAV_BYTES).content_type == "audio/wav"
    assert detect_audio_bytes(MP3_BYTES).content_type == "audio/mpeg"
    assert detect_audio_bytes(b"not-audio") is None


def test_finalize_success_and_audio_playback(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    search_id = str(uuid.uuid4())
    search_dir = tmp_path / "search"
    audio_dir = tmp_path / "audio"
    _write_search(search_dir, search_id)
    dummy = _DummyClient()
    dummy.deepseek = _DummyResponse(200, _deepseek_body({"reply_text": REPLY_TEXT}))
    dummy.tts = _DummyResponse(200, _tts_body("http://tts.example/result.mp3"))
    dummy.download = _DummyResponse(200, content=WAV_BYTES)
    _patch(monkeypatch, dummy, search_dir, audio_dir)

    response = client.post("/finalize", json={"search_id": search_id})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_text"] == REPLY_TEXT
    assert data["warning"] is None
    assert data["audio_url"].startswith("http://localhost:8003/audio/")
    audio_id = data["audio_url"].rsplit("/", 1)[-1]
    uuid.UUID(audio_id)

    user_prompt = dummy.posts[0][1]["messages"][1]["content"]
    assert SHOP_NAME in user_prompt
    assert "另一家不该出现的店" not in user_prompt
    assert dummy.posts[0][1]["thinking"] == {"type": "disabled"}
    assert dummy.posts[1][1]["input"]["voice"] == "Cherry"
    assert dummy.posts[1][1]["input"]["language_type"] == "Chinese"

    saved = json.loads((audio_dir / audio_id / "meta.json").read_text(encoding="utf-8"))
    assert saved["kind"] == "tts"
    assert saved["stored_name"] == "speech.wav"
    assert saved["content_type"] == "audio/wav"
    assert saved["created_at"]

    audio = client.get(f"/audio/{audio_id}")
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/wav")
    assert audio.content == WAV_BYTES


def test_finalize_keeps_text_when_tts_fails(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    search_id = str(uuid.uuid4())
    search_dir = tmp_path / "search"
    audio_dir = tmp_path / "audio"
    _write_search(search_dir, search_id)
    dummy = _DummyClient()
    dummy.deepseek = _DummyResponse(200, _deepseek_body({"reply_text": REPLY_TEXT}))
    dummy.tts_error = httpx.TimeoutException("timed out")
    _patch(monkeypatch, dummy, search_dir, audio_dir)

    response = client.post("/finalize", json={"search_id": search_id})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_text"] == REPLY_TEXT
    assert data["audio_url"] is None
    assert data["warning"] == "语音合成失败，已为你保留文字推荐。"


def test_finalize_keeps_text_when_download_format_unknown(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    search_id = str(uuid.uuid4())
    search_dir = tmp_path / "search"
    audio_dir = tmp_path / "audio"
    _write_search(search_dir, search_id)
    dummy = _DummyClient()
    dummy.deepseek = _DummyResponse(200, _deepseek_body({"reply_text": REPLY_TEXT}))
    dummy.tts = _DummyResponse(200, _tts_body("http://tts.example/result.wav"))
    dummy.download = _DummyResponse(200, content=b"this is not audio")
    _patch(monkeypatch, dummy, search_dir, audio_dir)

    response = client.post("/finalize", json={"search_id": search_id})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["audio_url"] is None
    assert data["warning"] == "语音合成失败，已为你保留文字推荐。"


def test_finalize_uses_magic_bytes_not_url_suffix(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    search_id = str(uuid.uuid4())
    search_dir = tmp_path / "search"
    audio_dir = tmp_path / "audio"
    _write_search(search_dir, search_id)
    dummy = _DummyClient()
    dummy.deepseek = _DummyResponse(200, _deepseek_body({"reply_text": REPLY_TEXT}))
    dummy.tts = _DummyResponse(200, _tts_body("http://tts.example/result.wav"))
    dummy.download = _DummyResponse(200, content=MP3_BYTES)
    _patch(monkeypatch, dummy, search_dir, audio_dir)

    response = client.post("/finalize", json={"search_id": search_id})
    assert response.status_code == 200
    audio_id = response.json()["data"]["audio_url"].rsplit("/", 1)[-1]
    saved = json.loads((audio_dir / audio_id / "meta.json").read_text(encoding="utf-8"))
    assert saved["stored_name"] == "speech.mp3"
    assert saved["content_type"] == "audio/mpeg"
    audio = client.get(f"/audio/{audio_id}")
    assert audio.headers["content-type"].startswith("audio/mpeg")


def test_finalize_reply_timeout(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    search_id = str(uuid.uuid4())
    search_dir = tmp_path / "search"
    _write_search(search_dir, search_id)
    dummy = _DummyClient()
    dummy.deepseek_error = httpx.TimeoutException("timed out")
    _patch(monkeypatch, dummy, search_dir, tmp_path / "audio")
    response = client.post("/finalize", json={"search_id": search_id})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert response.json()["error"]["stage"] == "finalize"


def test_finalize_reply_must_keep_shop_name(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    search_id = str(uuid.uuid4())
    search_dir = tmp_path / "search"
    _write_search(search_dir, search_id)
    dummy = _DummyClient()
    dummy.deepseek = _DummyResponse(
        200,
        _deepseek_body({"reply_text": "推荐你们去一家不错的店碰面。"}),
    )
    _patch(monkeypatch, dummy, search_dir, tmp_path / "audio")
    response = client.post("/finalize", json={"search_id": search_id})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_OUTPUT_INVALID"


def test_finalize_search_not_found(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_SEARCH_DIR", tmp_path / "search")
    response = client.post(
        "/finalize",
        json={"search_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "SEARCH_NOT_FOUND"
    assert body["error"]["stage"] == "finalize"


def test_finalize_search_expired(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    search_id = str(uuid.uuid4())
    search_dir = tmp_path / "search"
    expired = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    _write_search(search_dir, search_id, created_at=expired)
    monkeypatch.setattr("services.storage.DEFAULT_SEARCH_DIR", search_dir)
    response = client.post("/finalize", json={"search_id": search_id})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SEARCH_NOT_FOUND"


def test_finalize_missing_field(client: TestClient) -> None:
    response = client.post("/finalize", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["stage"] == "finalize"


def test_get_audio_not_found(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("services.storage.DEFAULT_AUDIO_DIR", tmp_path / "audio")
    response = client.get("/audio/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "AUDIO_NOT_FOUND"
    assert body["error"]["stage"] == "audio"
    assert "request_id" in body
