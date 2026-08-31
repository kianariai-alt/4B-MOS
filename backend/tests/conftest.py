import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import backend.app.models
from backend.app.db.base import Base
from backend.app.db.session import get_db
from backend.app.main import app


test_engine = create_engine(
    "sqlite://",
    connect_args={
        "check_same_thread": False,
    },
    poolclass=StaticPool,
)


@event.listens_for(test_engine, "connect")
def enable_sqlite_foreign_keys(
    dbapi_connection,
    connection_record,
):
    cursor = dbapi_connection.cursor()
    cursor.execute(
        "PRAGMA foreign_keys=ON"
    )
    cursor.close()


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


@pytest.fixture(autouse=True)
def reset_database():
    app.dependency_overrides[
        get_db
    ] = override_get_db

    Base.metadata.drop_all(
        bind=test_engine
    )

    Base.metadata.create_all(
        bind=test_engine
    )

    yield

    Base.metadata.drop_all(
        bind=test_engine
    )

    app.dependency_overrides.clear()


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session():
    db = TestingSessionLocal()

    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def admin_headers(client):
    bootstrap_response = client.post(
        "/api/v1/auth/bootstrap-admin",
        json={
            "username": "testadmin",
            "display_name": "Test Administrator",
            "password": "StrongAdmin123",
        },
    )

    assert bootstrap_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "testadmin",
            "password": "StrongAdmin123",
        },
    )

    assert login_response.status_code == 200

    token = login_response.json()[
        "access_token"
    ]

    return {
        "Authorization": f"Bearer {token}",
    }
@pytest.fixture
def authenticated_admin(
    client,
    admin_headers,
):
    client.headers.update(
        admin_headers
    )