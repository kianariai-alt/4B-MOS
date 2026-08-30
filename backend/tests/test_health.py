from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")

    assert response.status_code == 200

    data = response.json()

    assert data["application"] == "4B-MOS"
    assert data["version"] == "0.1.0"
    assert data["status"] == "running"
    assert data["api"] == "/api/v1"
    assert data["docs"] == "/docs"


def test_health_endpoint():
    response = client.get("/api/v1/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "healthy"
    assert data["application"] == "4B-MOS"
    assert data["version"] == "0.1.0"
    