from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app


test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestingSessionLocal = sessionmaker(
    bind=test_engine,
    autoflush=False,
    expire_on_commit=False,
)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)


def test_create_patient():
    response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "PAT-0001",
            "first_name": "Test",
            "last_name": "Patient",
            "date_of_birth": "1990-01-01",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["patient_code"] == "PAT-0001"
    assert data["first_name"] == "Test"
    assert data["last_name"] == "Patient"
    assert data["is_active"] is True
    assert "id" in data


def test_duplicate_patient_code_returns_conflict():
    payload = {
        "patient_code": "PAT-0002",
        "first_name": "Test",
        "last_name": "Patient",
    }

    first_response = client.post("/api/v1/patients", json=payload)
    second_response = client.post("/api/v1/patients", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_get_patient():
    create_response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "PAT-0003",
            "first_name": "Kian",
            "last_name": "Test",
        },
    )

    patient_id = create_response.json()["id"]

    response = client.get(
        f"/api/v1/patients/{patient_id}"
    )

    assert response.status_code == 200
    assert response.json()["patient_code"] == "PAT-0003"


def test_list_patients():
    client.post(
        "/api/v1/patients",
        json={
            "patient_code": "PAT-0004",
            "first_name": "First",
            "last_name": "Patient",
        },
    )

    client.post(
        "/api/v1/patients",
        json={
            "patient_code": "PAT-0005",
            "first_name": "Second",
            "last_name": "Patient",
        },
    )

    response = client.get("/api/v1/patients")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_update_patient():
    create_response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "PAT-0006",
            "first_name": "Before",
            "last_name": "Update",
        },
    )

    patient_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/patients/{patient_id}",
        json={"first_name": "After"},
    )

    assert response.status_code == 200
    assert response.json()["first_name"] == "After"


def test_deactivate_patient():
    create_response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "PAT-0007",
            "first_name": "Active",
            "last_name": "Patient",
        },
    )

    patient_id = create_response.json()["id"]

    response = client.delete(
        f"/api/v1/patients/{patient_id}"
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_missing_patient_returns_404():
    response = client.get(
        "/api/v1/patients/not-a-real-id"
    )

    assert response.status_code == 404