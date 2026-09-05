from pathlib import Path
import json
import uuid

import httpx
from fastapi.testclient import TestClient

from services.amap import AROUND_TIMEOUT_SECONDS, GEOCODE_TIMEOUT_SECONDS
from services.geo import haversine_m, midpoint, parse_location
from services.search import SEARCH_TOTAL_TIMEOUT_SECONDS

OK_BODY = {
    "city_a": "杭州",
    "address_a": "杭州东站",
    "city_b": "杭州",
    "address_b": "西湖龙翔桥地铁站",
    "category": "咖啡店",
}

LNG_A, LAT_A = 120.200000, 30.200000
LNG_B, LAT_B = 120.400000, 30.400000
MID_LNG, MID_LAT = midpoint(LNG_A, LAT_A, LNG_B, LAT_B)


class _DummyResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _DummyClient:
    def __init__(self, handler=None, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._handler = handler
        self._error = error

    async def __aenter__(self) -> "_DummyClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url, params=None):
        self.calls.append((url, dict(params or {})))
        if self._error:
            raise self._error
        assert self._handler is not None
        return self._handler(url, params or {})


def _amap_ok(*, geocodes=None, pois=None) -> dict:
    payload = {"status": "1", "infocode": "10000"}
    if geocodes is not None:
        payload["geocodes"] = geocodes
    if pois is not None:
        payload["pois"] = pois
    return payload


def _geocode(
    formatted: str,
    location: str,
    *,
    level: str = "兴趣点",
    city: str | list = "杭州市",
    province: str = "浙江省",
) -> dict:
    return {
        "formatted_address": formatted,
        "location": location,
        "level": level,
        "city": city,
        "province": province,
    }


def _poi(
    name: str,
    address: str,
    location: str,
    distance: object = "100",
    cityname: str | list = "杭州市",
) -> dict:
    return {
        "name": name,
        "address": address,
        "location": location,
        "distance": distance,
        "cityname": cityname,
    }


def _handler(geocode_map: dict[str, list], around_map: dict[str, list]):
    def handle(url: str, params: dict) -> _DummyResponse:
        if "geocode/geo" in url:
            return _DummyResponse(200, _amap_ok(geocodes=geocode_map[params["address"]]))
        return _DummyResponse(200, _amap_ok(pois=around_map.get(params["radius"], [])))

    return handle


def _patch_client(monkeypatch, dummy: _DummyClient, tmp_path: Path) -> None:
    monkeypatch.setattr("services.amap.settings.amap_api_key", "test-key")
    monkeypatch.setattr("services.amap.httpx.AsyncClient", lambda timeout: dummy)
    monkeypatch.setattr("services.storage.DEFAULT_SEARCH_DIR", tmp_path)


def test_location_order_is_lng_then_lat() -> None:
    parsed = parse_location("120.210123,30.274456")
    assert parsed == (120.210123, 30.274456)


def test_midpoint_is_arithmetic_mean() -> None:
    lng, lat = midpoint(120.2, 30.2, 120.4, 30.4)
    assert lng == 120.3
    assert lat == 30.3


def test_search_timeout_budget() -> None:
    assert GEOCODE_TIMEOUT_SECONDS == 4.0
    assert AROUND_TIMEOUT_SECONDS == 4.0
    assert SEARCH_TOTAL_TIMEOUT_SECONDS == 20.0


def test_search_success_sorts_and_saves(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    geocode_map = {
        "杭州东站": [
            _geocode("浙江省杭州市上城区杭州东站", f"{LNG_A},{LAT_A}", level="公交地铁站点"),
        ],
        "西湖龙翔桥地铁站": [
            _geocode("浙江省杭州市西湖区龙翔桥地铁站", f"{LNG_B},{LAT_B}", level="公交地铁站点"),
        ],
    }
    around_map = {
        "2000": [
            _poi("远的店", "杭州市上城区远路9号", f"{MID_LNG},{MID_LAT}", distance="800"),
            _poi("近的店", "杭州市上城区近路1号", f"{MID_LNG},{MID_LAT}", distance="100"),
            _poi("中的店", "杭州市上城区中路5号", f"{MID_LNG},{MID_LAT}", distance="400"),
            _poi("更近的店", "杭州市上城区近路2号", f"{MID_LNG},{MID_LAT}", distance="50"),
            _poi("", "缺名称应被丢掉", f"{MID_LNG},{MID_LAT}", distance="10"),
        ]
    }
    dummy = _DummyClient(handler=_handler(geocode_map, around_map))
    _patch_client(monkeypatch, dummy, tmp_path)

    response = client.post("/search", json=OK_BODY)
    assert response.status_code == 200
    data = response.json()["data"]
    uuid.UUID(data["search_id"])
    assert data["midpoint"] == {"longitude": MID_LNG, "latitude": MID_LAT}
    assert [poi["name"] for poi in data["pois"]] == ["更近的店", "近的店", "中的店"]
    assert [poi["distance_to_midpoint_m"] for poi in data["pois"]] == [50, 100, 400]
    assert len(data["pois"]) == 3

    radii = [params["radius"] for url, params in dummy.calls if "place/around" in url]
    assert radii == ["2000"]

    saved = tmp_path / data["search_id"] / "result.json"
    record = json.loads(saved.read_text(encoding="utf-8"))
    assert record["search_id"] == data["search_id"]
    assert record["created_at"]
    assert record["radius_m"] == 2000
    assert record["midpoint"] == data["midpoint"]


def test_search_missing_distance_uses_haversine_not_zero(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    poi_lng, poi_lat = MID_LNG + 0.01, MID_LAT
    geocode_map = {
        "杭州东站": [_geocode("浙江省杭州市上城区杭州东站", f"{LNG_A},{LAT_A}")],
        "西湖龙翔桥地铁站": [_geocode("浙江省杭州市西湖区龙翔桥地铁站", f"{LNG_B},{LAT_B}")],
    }
    around_map = {
        "2000": [
            _poi("缺距离的店", "杭州市上城区某路1号", f"{poi_lng},{poi_lat}", distance=[]),
        ]
    }
    dummy = _DummyClient(handler=_handler(geocode_map, around_map))
    _patch_client(monkeypatch, dummy, tmp_path)

    response = client.post("/search", json=OK_BODY)
    assert response.status_code == 200
    distance = response.json()["data"]["pois"][0]["distance_to_midpoint_m"]
    expected = round(haversine_m(poi_lng, poi_lat, MID_LNG, MID_LAT))
    assert distance == expected
    assert distance != 0


def test_search_expands_to_5000_when_2000_empty(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    geocode_map = {
        "杭州东站": [_geocode("浙江省杭州市上城区杭州东站", f"{LNG_A},{LAT_A}")],
        "西湖龙翔桥地铁站": [_geocode("浙江省杭州市西湖区龙翔桥地铁站", f"{LNG_B},{LAT_B}")],
    }
    around_map = {
        "2000": [],
        "5000": [_poi("扩大后的店", "杭州市上城区某路1号", f"{MID_LNG},{MID_LAT}", distance="3200")],
    }
    dummy = _DummyClient(handler=_handler(geocode_map, around_map))
    _patch_client(monkeypatch, dummy, tmp_path)

    response = client.post("/search", json=OK_BODY)
    assert response.status_code == 200
    assert response.json()["data"]["pois"][0]["name"] == "扩大后的店"
    radii = [params["radius"] for url, params in dummy.calls if "place/around" in url]
    assert radii == ["2000", "5000"]


def test_search_geo_unresolved(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    geocode_map = {
        "杭州东站": [
            _geocode("浙江省杭州市", f"{LNG_A},{LAT_A}", level="市"),
        ],
        "西湖龙翔桥地铁站": [_geocode("浙江省杭州市西湖区龙翔桥地铁站", f"{LNG_B},{LAT_B}")],
    }
    dummy = _DummyClient(handler=_handler(geocode_map, {}))
    _patch_client(monkeypatch, dummy, tmp_path)

    response = client.post("/search", json=OK_BODY)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "GEO_UNRESOLVED"
    assert body["error"]["stage"] == "search"
    assert not (tmp_path / "result.json").exists()
    assert not any("place/around" in url for url, _ in dummy.calls)


def test_search_geo_ambiguous_does_not_merge_300m(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    # Same core toponym, but ~300m and ~1000m apart. All pairs are checked; 300m is not merged.
    far_lat = LAT_A + (300 / 111_320)
    farther_lat = LAT_A + (1000 / 111_320)
    geocode_map = {
        "杭州东站": [
            _geocode("浙江省杭州市上城区杭州东站", f"{LNG_A},{LAT_A}", level="公交地铁站点"),
            _geocode("杭州市上城区杭州东站", f"{LNG_A},{far_lat}", level="公交地铁站点"),
            _geocode("浙江省杭州市江干区杭州东站", f"{LNG_A},{farther_lat}", level="公交地铁站点"),
        ],
        "西湖龙翔桥地铁站": [_geocode("浙江省杭州市西湖区龙翔桥地铁站", f"{LNG_B},{LAT_B}")],
    }
    dummy = _DummyClient(handler=_handler(geocode_map, {}))
    _patch_client(monkeypatch, dummy, tmp_path)

    response = client.post("/search", json=OK_BODY)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "GEO_AMBIGUOUS"
    assert body["error"]["message"] == "找到多个可能的地点，请补充更具体的站名、出入口或地址。"
    assert body["error"]["stage"] == "search"


def test_search_merges_only_within_150m_same_name(
    client: TestClient, monkeypatch, tmp_path: Path
) -> None:
    near_lat = LAT_A + (80 / 111_320)
    geocode_map = {
        "杭州东站": [
            _geocode("浙江省杭州市上城区杭州东站", f"{LNG_A},{LAT_A}", level="公交地铁站点"),
            _geocode("杭州市上城区杭州东站", f"{LNG_A},{near_lat}", level="兴趣点"),
        ],
        "西湖龙翔桥地铁站": [_geocode("浙江省杭州市西湖区龙翔桥地铁站", f"{LNG_B},{LAT_B}")],
    }
    around_map = {
        "2000": [_poi("某咖啡店", "杭州市上城区湖滨路1号", f"{MID_LNG},{MID_LAT}", distance="320")],
    }
    dummy = _DummyClient(handler=_handler(geocode_map, around_map))
    _patch_client(monkeypatch, dummy, tmp_path)

    response = client.post("/search", json=OK_BODY)
    assert response.status_code == 200
    assert response.json()["data"]["pois"][0]["name"] == "某咖啡店"


def test_search_no_poi(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    geocode_map = {
        "杭州东站": [_geocode("浙江省杭州市上城区杭州东站", f"{LNG_A},{LAT_A}")],
        "西湖龙翔桥地铁站": [_geocode("浙江省杭州市西湖区龙翔桥地铁站", f"{LNG_B},{LAT_B}")],
    }
    around_map = {"2000": [], "5000": []}
    dummy = _DummyClient(handler=_handler(geocode_map, around_map))
    _patch_client(monkeypatch, dummy, tmp_path)

    response = client.post("/search", json=OK_BODY)
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "NO_POI"
    assert body["error"]["stage"] == "search"
    radii = [params["radius"] for url, params in dummy.calls if "place/around" in url]
    assert radii == ["2000", "5000"]


def test_search_timeout(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    dummy = _DummyClient(error=httpx.TimeoutException("timed out"))
    _patch_client(monkeypatch, dummy, tmp_path)
    response = client.post("/search", json=OK_BODY)
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert response.json()["error"]["stage"] == "search"


def test_search_upstream_error(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    def handle(url: str, params: dict) -> _DummyResponse:
        return _DummyResponse(200, {"status": "0", "infocode": "10001"})

    dummy = _DummyClient(handler=handle)
    _patch_client(monkeypatch, dummy, tmp_path)
    response = client.post("/search", json=OK_BODY)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_ERROR"


def test_search_missing_api_key(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("services.amap.settings.amap_api_key", "")
    monkeypatch.setattr("services.storage.DEFAULT_SEARCH_DIR", tmp_path)
    response = client.post("/search", json=OK_BODY)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_ERROR"


def test_search_missing_request_field(client: TestClient) -> None:
    response = client.post("/search", json={"city_a": "杭州", "address_a": "杭州东站"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["stage"] == "search"
