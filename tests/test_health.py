from fastapi.testclient import TestClient

from totoro_ai.api.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "name" in data
    assert "version" in data
