from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert "request_id" in body
    assert body["request_id"]
    assert body["data"] == {"status": "ok"}
    assert response.headers.get("X-Request-ID") == body["request_id"]
