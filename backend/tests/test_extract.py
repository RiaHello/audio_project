import json

import httpx
from fastapi.testclient import TestClient


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


class _DummyResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
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


def _patch_client(monkeypatch, dummy: _DummyClient) -> None:
    monkeypatch.setattr("services.extract.settings.deepseek_api_key", "sk-test")
    monkeypatch.setattr("services.extract.httpx.AsyncClient", lambda timeout: dummy)


def test_extract_success_returns_five_fields(client: TestClient, monkeypatch) -> None:
    raw = {
        "city_a": "杭州",
        "address_a": "杭州东站",
        "city_b": "杭州市",
        "address_b": "西湖龙翔桥地铁站",
        "category": "咖啡店",
        "party_count": 2,
        "incomplete_reason": None,
    }
    dummy = _DummyClient(response=_DummyResponse(200, _deepseek_body(raw)))
    _patch_client(monkeypatch, dummy)

    response = client.post(
        "/extract",
        json={
            "text": "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。",
            "city": "杭州",
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {
        "city_a": "杭州",
        "address_a": "杭州东站",
        "city_b": "杭州",
        "address_b": "西湖龙翔桥地铁站",
        "category": "咖啡店",
    }
    assert "party_count" not in data
    assert dummy.posted_json["thinking"] == {"type": "disabled"}
    assert dummy.posted_json["response_format"] == {"type": "json_object"}


def test_extract_missing_address(client: TestClient, monkeypatch) -> None:
    raw = {
        "city_a": "杭州",
        "address_a": "杭州东站",
        "city_b": "杭州",
        "address_b": None,
        "category": "咖啡店",
        "party_count": 2,
        "incomplete_reason": "missing_address",
    }
    dummy = _DummyClient(response=_DummyResponse(200, _deepseek_body(raw)))
    _patch_client(monkeypatch, dummy)
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友也过来，找个咖啡店。", "city": "杭州"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "EXTRACT_INCOMPLETE"
    assert body["error"]["stage"] == "extract"


def test_extract_party_count_invalid(client: TestClient, monkeypatch) -> None:
    raw = {
        "city_a": "杭州",
        "address_a": "杭州东站",
        "city_b": "杭州",
        "address_b": "龙翔桥地铁站",
        "category": "咖啡店",
        "party_count": 3,
        "incomplete_reason": "party_count",
    }
    dummy = _DummyClient(response=_DummyResponse(200, _deepseek_body(raw)))
    _patch_client(monkeypatch, dummy)
    response = client.post(
        "/extract",
        json={
            "text": "我、小李和小王，我在杭州东站，他们在龙翔桥地铁站。",
            "city": "杭州",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PARTY_COUNT_INVALID"


def test_extract_cross_city(client: TestClient, monkeypatch) -> None:
    raw = {
        "city_a": "杭州",
        "address_a": "杭州东站",
        "city_b": "上海",
        "address_b": "虹桥火车站",
        "category": "咖啡店",
        "party_count": 2,
        "incomplete_reason": "cross_city",
    }
    dummy = _DummyClient(response=_DummyResponse(200, _deepseek_body(raw)))
    _patch_client(monkeypatch, dummy)
    response = client.post(
        "/extract",
        json={
            "text": "我在杭州东站，朋友在上海虹桥火车站，找个咖啡店。",
            "city": "杭州",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CROSS_CITY"


def test_extract_vague_home_address(client: TestClient, monkeypatch) -> None:
    raw = {
        "city_a": "杭州",
        "address_a": "我家",
        "city_b": "杭州",
        "address_b": "杭州东站",
        "category": "咖啡店",
        "party_count": 2,
        "incomplete_reason": None,
    }
    dummy = _DummyClient(response=_DummyResponse(200, _deepseek_body(raw)))
    _patch_client(monkeypatch, dummy)
    response = client.post(
        "/extract",
        json={"text": "我在我家，朋友在杭州东站，找咖啡店。", "city": "杭州"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EXTRACT_INCOMPLETE"


def test_extract_invalid_json_is_model_error(client: TestClient, monkeypatch) -> None:
    dummy = _DummyClient(response=_DummyResponse(200, _deepseek_body("not-json")))
    _patch_client(monkeypatch, dummy)
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友在龙翔桥。", "city": "杭州"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_OUTPUT_INVALID"


def test_extract_missing_model_field_is_model_error(client: TestClient, monkeypatch) -> None:
    raw = {
        "city_a": "杭州",
        "address_a": "杭州东站",
        "city_b": "杭州",
        "category": "咖啡店",
        "party_count": 2,
        "incomplete_reason": None,
    }
    dummy = _DummyClient(response=_DummyResponse(200, _deepseek_body(raw)))
    _patch_client(monkeypatch, dummy)
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友在龙翔桥。", "city": "杭州"},
    )
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "MODEL_OUTPUT_INVALID"


def test_extract_timeout(client: TestClient, monkeypatch) -> None:
    dummy = _DummyClient(error=httpx.TimeoutException("timed out"))
    _patch_client(monkeypatch, dummy)
    response = client.post(
        "/extract",
        json={"text": "我在杭州东站，朋友在龙翔桥。", "city": "杭州"},
    )
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "UPSTREAM_TIMEOUT"


def test_extract_missing_request_field(client: TestClient) -> None:
    response = client.post("/extract", json={"text": "你好"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["stage"] == "extract"
