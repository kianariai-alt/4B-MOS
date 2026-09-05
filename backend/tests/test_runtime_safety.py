from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from backend.app.core.config import Settings, settings
from backend.app.core.database_revision import EXPECTED_DATABASE_REVISION
from backend.app.core.security import decode_access_token
from backend.app.db.base import Base
from backend.app.main import create_application
from backend.app.models.user import User
from backend.app.schemas.auth import BootstrapAdminRequest
from backend.app.services.auth import AuthService, BootstrapAlreadyCompletedError


def production_settings(**overrides):
    return Settings(_env_file=None, **{
        "ENVIRONMENT": "production", "DEBUG": False, "BOOTSTRAP_ENABLED": False,
        "SECRET_KEY": "TEST-ONLY-key-0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        **overrides,
    })


@pytest.mark.parametrize("override", [
    {"DEBUG": True}, {"BOOTSTRAP_ENABLED": True}, {"SECRET_KEY": "short"},
    {"SECRET_KEY": "x" * 64}, {"SECRET_KEY": "4bmos-development-secret-change-before-production"},
    {"JWT_ALGORITHM": "none"}, {"ACCESS_TOKEN_EXPIRE_MINUTES": 0},
])
def test_production_rejects_unsafe_configuration(override):
    with pytest.raises(ValidationError) as result:
        production_settings(**override)
    assert "TEST-ONLY-key" not in str(result.value)


def test_valid_production_configuration_and_hidden_docs(monkeypatch):
    assert production_settings().ENVIRONMENT == "production"
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with TestClient(create_application()) as client:
        for url in ["/docs", "/redoc", "/openapi.json"]:
            assert client.get(url).status_code == 404


@pytest.mark.parametrize("field", ["sub", "iat", "exp", "ver"])
def test_signed_token_must_contain_required_claims(field):
    now = datetime.now(timezone.utc)
    claims = {"sub": "user", "iat": now, "exp": now + timedelta(minutes=1), "ver": 0}
    del claims[field]
    token = jwt.encode(claims, settings.SECRET_KEY, algorithm="HS256")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token)


@pytest.mark.parametrize("environment,enabled", [("production", True), ("development", False)])
def test_bootstrap_disabled_without_creating_users(client, db_session, monkeypatch, environment, enabled):
    monkeypatch.setattr(settings, "ENVIRONMENT", environment)
    monkeypatch.setattr(settings, "BOOTSTRAP_ENABLED", enabled)
    response = client.post("/api/v1/auth/bootstrap-admin", json={
        "username": "newadmin", "display_name": "Admin", "password": "StrongAdmin123",
    })
    assert response.status_code == 403
    assert db_session.scalar(select(func.count()).select_from(User)) == 0


def test_bootstrap_two_connections_cannot_create_two_admins(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'bootstrap.db'}", connect_args={"timeout": 0.1})
    Base.metadata.create_all(engine)
    import backend.app.services.auth as auth_module
    original = auth_module.hash_password
    entered, release = Event(), Event()
    def paused_hash(password):
        entered.set()
        assert release.wait(5)
        return original(password)
    monkeypatch.setattr(auth_module, "hash_password", paused_hash)
    def create(username):
        with Session(engine) as db:
            AuthService.bootstrap_admin(db, BootstrapAdminRequest(
                username=username, display_name="Test", password="StrongAdmin123",
            ))
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(create, "firstadmin")
            try:
                assert entered.wait(5)
                with pytest.raises(BootstrapAlreadyCompletedError):
                    create("secondadmin")
            finally:
                release.set()
            future.result(timeout=5)
        with pytest.raises(BootstrapAlreadyCompletedError):
            create("secondadmin")
        with Session(engine) as db:
            assert list(db.scalars(select(User.username))) == ["firstadmin"]
    finally:
        engine.dispose()


@pytest.mark.parametrize("revision", [None, "old-version", EXPECTED_DATABASE_REVISION])
def test_readiness_requires_expected_schema(client, db_session, revision):
    if revision is not None:
        db_session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        db_session.execute(text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision})
        db_session.commit()
    try:
        result = client.get("/api/v1/health/ready")
        assert result.status_code == (200 if revision == EXPECTED_DATABASE_REVISION else 503)
        assert result.json() == {"status": "ready" if result.status_code == 200 else "not_ready"}
        assert client.get("/api/v1/health").status_code == 200
    finally:
        if revision is not None:
            db_session.execute(text("DROP TABLE alembic_version"))
            db_session.commit()
