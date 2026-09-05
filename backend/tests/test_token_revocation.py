from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.models.audit_log import AuditLog
from backend.app.models.user import User


def login(client, username, password):
    response = client.post("/api/v1/auth/login", json={
        "username": username,
        "password": password,
    })
    assert response.status_code == 200
    return response.json()["access_token"]


def create_user(client, admin_headers, *, username="doctor1", role="physician"):
    response = client.post("/api/v1/users", headers=admin_headers, json={
        "username": username,
        "display_name": "Doctor One",
        "password": "StrongPass123",
        "role": role,
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_login_token_contains_account_version(client, admin_headers):
    token = login(client, "testadmin", "StrongAdmin123")
    claims = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    assert claims["ver"] == 0


@pytest.mark.parametrize("version", ["0", True, -1])
def test_malformed_account_version_is_rejected(client, admin_headers, version):
    user_id = client.get("/api/v1/auth/me", headers=admin_headers).json()["id"]
    now = datetime.now(timezone.utc)
    token = jwt.encode({
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=1),
        "ver": version,
    }, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_display_name_change_keeps_existing_token_valid(client, admin_headers):
    user_id = create_user(client, admin_headers)
    token = login(client, "doctor1", "StrongPass123")
    response = client.patch(
        f"/api/v1/users/{user_id}", headers=admin_headers,
        json={"display_name": "Updated Doctor"},
    )
    assert response.status_code == 200
    assert client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 200


@pytest.mark.parametrize("change", [
    {"password": "NewPassword456"},
    {"role": "viewer"},
    {"is_active": False},
])
def test_security_change_revokes_existing_token(client, admin_headers, db_session, change):
    user_id = create_user(client, admin_headers)
    token = login(client, "doctor1", "StrongPass123")
    response = client.patch(f"/api/v1/users/{user_id}", headers=admin_headers, json=change)
    assert response.status_code == 200
    revoked = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert revoked.status_code == 401
    assert revoked.json()["detail"] == "Access token is no longer valid."
    db_session.expire_all()
    user = db_session.get(User, user_id)
    assert user.auth_version == 1
    audit = db_session.scalar(select(AuditLog).where(
        AuditLog.entity_type == "user",
        AuditLog.entity_id == user_id,
        AuditLog.event_type == "user_updated",
    ).order_by(AuditLog.created_at.desc()))
    assert audit.event_data["sessions_revoked"] is True
    assert "auth_version" not in audit.event_data["changed_fields"]


def test_new_token_works_after_password_reset(client, admin_headers):
    user_id = create_user(client, admin_headers)
    old_token = login(client, "doctor1", "StrongPass123")
    assert client.patch(
        f"/api/v1/users/{user_id}", headers=admin_headers,
        json={"password": "NewPassword456"},
    ).status_code == 200
    assert client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_token}"}
    ).status_code == 401
    new_token = login(client, "doctor1", "NewPassword456")
    assert client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"}
    ).status_code == 200


def test_reactivation_does_not_restore_pre_disable_token(client, admin_headers):
    user_id = create_user(client, admin_headers)
    token = login(client, "doctor1", "StrongPass123")
    for active in (False, True):
        assert client.patch(
            f"/api/v1/users/{user_id}", headers=admin_headers,
            json={"is_active": active},
        ).status_code == 200
    assert client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 401
    assert client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login(client, 'doctor1', 'StrongPass123')}"},
    ).status_code == 200
