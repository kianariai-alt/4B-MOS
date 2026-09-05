import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models.audit_log import AuditLog
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.auth import BootstrapAdminRequest
from backend.app.schemas.user import UserCreate, UserUpdate
from backend.app.services.auth import AuthService
from backend.app.services.user import UserService
from backend.app.db.account_transactions import AccountWriteConflictError
from backend.tests.test_last_active_admin import account_engine, admin_id
from backend.tests.test_user_management_rbac import create_and_login_user


def test_account_history_records_changes_without_password_values(client, admin_headers, db_session):
    response = client.post("/api/v1/users", headers=admin_headers, json={
        "username": "audited", "display_name": "Original", "password": "OriginalSecret123", "role": "viewer",
    })
    assert response.status_code == 201
    user_id = response.json()["id"]
    old_hash = db_session.get(User, user_id).password_hash
    response = client.patch(f"/api/v1/users/{user_id}", headers=admin_headers, json={
        "display_name": "Updated", "role": "nurse", "is_active": False, "password": "NewSecret456",
    })
    assert response.status_code == 200
    result = client.get(f"/api/v1/users/{user_id}/audit-logs", headers=admin_headers)
    assert result.status_code == 200
    logs = result.json()
    assert [row["event_type"] for row in logs] == ["user_created", "user_updated"]
    assert logs[0]["event_data"]["after"]["username"] == "audited"
    update = logs[1]
    assert update["actor_username"] == "testadmin"
    assert update["actor_role"] == "admin"
    assert update["event_data"] == {
        "schema_version": 1, "source": "authenticated_admin",
        "changed_fields": ["display_name", "is_active", "password", "role"],
        "before": {"display_name": "Original", "is_active": True, "role": "viewer"},
        "after": {"display_name": "Updated", "is_active": False, "role": "nurse"},
        "password_reset": True,
    }
    db_session.expire_all()
    for secret in ["OriginalSecret123", "NewSecret456", old_hash, db_session.get(User, user_id).password_hash, "password_hash"]:
        assert secret not in json.dumps(logs)


def test_self_demotion_keeps_pre_change_actor_attribution(client, admin_headers, db_session):
    second, second_headers = create_and_login_user(client, admin_headers, username="nextadmin", role="admin")
    first = db_session.scalar(select(User).where(User.username == "testadmin"))
    old_name = first.display_name
    response = client.patch(f"/api/v1/users/{first.id}", headers=admin_headers,
                            json={"role": "viewer", "display_name": "Former admin"})
    assert response.status_code == 200
    logs = client.get(f"/api/v1/users/{first.id}/audit-logs", headers=second_headers).json()
    event = logs[-1]
    assert event["actor_role"] == "admin"
    assert event["actor_display_name"] == old_name
    assert event["event_data"]["after"]["role"] == "viewer"
    assert client.get(f"/api/v1/users/{first.id}/audit-logs", headers=admin_headers).status_code == 403


def test_noop_patch_does_not_create_fake_events_or_change_timestamp(client, admin_headers, db_session):
    admin = db_session.scalar(select(User).where(User.username == "testadmin"))
    original_timestamp = admin.updated_at
    before = db_session.scalar(select(func.count()).select_from(AuditLog))
    for payload in [{}, {"display_name": admin.display_name, "role": "admin", "is_active": True}]:
        assert client.patch(f"/api/v1/users/{admin.id}", headers=admin_headers, json=payload).status_code == 200
    db_session.expire_all()
    assert admin.updated_at == original_timestamp
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == before


def test_bootstrap_event_does_not_invent_authenticated_actor(client, admin_headers, db_session):
    admin = db_session.scalar(select(User).where(User.username == "testadmin"))
    log = client.get(f"/api/v1/users/{admin.id}/audit-logs", headers=admin_headers).json()[0]
    assert log["event_type"] == "admin_bootstrapped"
    assert log["actor_user_id"] is None and log["actor_role"] is None
    assert log["event_data"]["source"] == "unauthenticated_bootstrap"
    assert "password" not in json.dumps(log)


@pytest.mark.parametrize("operation", ["bootstrap", "create", "update"])
@pytest.mark.parametrize("failure", ["before_audit", "after_audit", "commit"])
def test_account_and_audit_roll_back_together(db_session, monkeypatch, operation, failure):
    seeded = None
    original_hash = None
    if operation != "bootstrap":
        seeded = UserService.create_user(db_session, UserCreate(
            username="existing", display_name="Before", password="BeforePassword123", role="admin",
        ))
        original_hash = seeded.password_hash
    audit_count = db_session.scalar(select(func.count()).select_from(AuditLog))
    original_audit = AuditLogRepository.create
    def fail_audit(*args, **kwargs):
        if failure == "after_audit":
            original_audit(*args, **kwargs)
        raise RuntimeError("injected audit failure")
    def fail_commit():
        raise RuntimeError("injected commit failure")
    if failure == "commit":
        monkeypatch.setattr(db_session, "commit", fail_commit)
    else:
        monkeypatch.setattr(AuditLogRepository, "create", staticmethod(fail_audit))
    with pytest.raises(RuntimeError, match="injected"):
        if operation == "bootstrap":
            AuthService.bootstrap_admin(db_session, BootstrapAdminRequest(
                username="bootstrap", display_name="Admin", password="StrongPassword123",
            ))
        elif operation == "create":
            UserService.create_user(db_session, UserCreate(
                username="newaccount", display_name="New", password="StrongPassword123",
            ), actor=seeded)
        else:
            UserService.update_user(db_session, seeded.id, UserUpdate(
                display_name="After", password="AfterPassword456",
            ), actor=seeded)
    assert not db_session.in_transaction()
    with Session(db_session.get_bind()) as observer:
        assert observer.scalar(select(func.count()).select_from(AuditLog)) == audit_count
        users = list(observer.scalars(select(User)))
        assert len(users) == (0 if operation == "bootstrap" else 1)
        if users:
            assert users[0].display_name == "Before"
            assert users[0].password_hash == original_hash


@pytest.mark.parametrize("role", ["physician", "nurse", "operator", "viewer"])
def test_non_admins_cannot_read_account_history(client, admin_headers, role):
    user, headers = create_and_login_user(client, admin_headers, username="reader_" + role, role=role)
    assert client.get(f"/api/v1/users/{user['id']}/audit-logs", headers=headers).status_code == 403


def test_audit_endpoint_auth_pagination_and_entity_isolation(client, admin_headers, db_session):
    admin = db_session.scalar(select(User).where(User.username == "testadmin"))
    url = f"/api/v1/users/{admin.id}/audit-logs"
    assert client.get(url).status_code == 401
    assert client.get("/api/v1/users/unknown/audit-logs", headers=admin_headers).status_code == 404
    for name in ["Name one", "Name two"]:
        assert client.patch(f"/api/v1/users/{admin.id}", headers=admin_headers, json={"display_name": name}).status_code == 200
    all_logs = client.get(url, headers=admin_headers).json()
    assert len(all_logs) == 3
    assert client.get(url + "?skip=1&limit=1", headers=admin_headers).json() == all_logs[1:2]
    assert client.get(url + "?skip=100", headers=admin_headers).json() == []
    for query in ["skip=-1", "limit=0", "limit=501"]:
        assert client.get(url + "?" + query, headers=admin_headers).status_code == 422
    other, _ = create_and_login_user(client, admin_headers, username="other_account", role="viewer")
    other_logs = client.get(f"/api/v1/users/{other['id']}/audit-logs", headers=admin_headers).json()
    assert len(other_logs) == 1 and other_logs[0]["entity_id"] == other["id"]


def test_denied_last_admin_edit_does_not_emit_success_event(client, admin_headers, db_session):
    admin = db_session.scalar(select(User).where(User.username == "testadmin"))
    before = db_session.scalar(select(func.count()).select_from(AuditLog))
    assert client.patch(f"/api/v1/users/{admin.id}", headers=admin_headers, json={"is_active": False}).status_code == 409
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == before


def test_account_lock_is_held_until_audit_commit(account_engine, monkeypatch):
    engine, first, second = account_engine
    entered, release = Event(), Event()
    original = AuditLogRepository.create
    def paused_audit(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(AuditLogRepository, "create", staticmethod(paused_audit))
    def change(user_id, name):
        with Session(engine) as db:
            UserService.update_user(db, user_id, UserUpdate(display_name=name), actor=db.get(User, user_id))
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(change, first, "committed first")
        try:
            assert entered.wait(5)
            with pytest.raises(AccountWriteConflictError):
                change(second, "must not persist")
        finally:
            release.set()
        future.result(timeout=5)
    with Session(engine) as observer:
        assert observer.get(User, first).display_name == "committed first"
        assert observer.get(User, second).display_name != "must not persist"
        events = list(observer.scalars(select(AuditLog).where(AuditLog.event_type == "user_updated")))
        assert len(events) == 1
        assert events[0].event_data["after"]["display_name"] == "committed first"
