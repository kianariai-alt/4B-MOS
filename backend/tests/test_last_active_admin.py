from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import sqlite3
from threading import Event

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.db.account_transactions import AccountAuthorizationError, AccountWriteConflictError
from backend.app.models.user import User
from backend.app.repositories.user import UserRepository
from backend.app.schemas.user import UserCreate, UserUpdate
from backend.app.services.user import LastActiveAdminError, UserService


@pytest.fixture
def admin_id(admin_headers, db_session):
    return db_session.scalar(select(User.id).where(User.username == "testadmin"))


def add_admin(db, name="secondadmin"):
    return UserService.create_user(db, UserCreate(
        username=name, display_name=name, password="StrongPassword123", role="admin",
    )).id


@pytest.mark.parametrize("payload", [{"role": "viewer"}, {"is_active": False}, {"role": "nurse", "is_active": False}])
def test_last_admin_change_is_conflict_without_partial_edits(client, admin_headers, admin_id, db_session, payload):
    response = client.patch(f"/api/v1/users/{admin_id}", headers=admin_headers,
                            json={**payload, "display_name": "must not change"})
    assert response.status_code == 409
    db_session.expire_all()
    user = db_session.get(User, admin_id)
    assert user.role == "admin" and user.is_active
    assert user.display_name != "must not change"
    assert client.get("/api/v1/users", headers=admin_headers).status_code == 200


def test_inactive_admin_does_not_count_as_successor(client, admin_headers, admin_id, db_session):
    second = add_admin(db_session)
    UserService.update_user(db_session, second, UserUpdate(is_active=False))
    assert client.patch(f"/api/v1/users/{admin_id}", headers=admin_headers, json={"role": "viewer"}).status_code == 409


@pytest.mark.parametrize("payload", [{}, {"role": "admin", "is_active": True}, {"display_name": "Renamed admin"}, {"password": "NewStrongPassword456"}])
def test_last_admin_can_make_safe_updates(client, admin_headers, admin_id, payload):
    assert client.patch(f"/api/v1/users/{admin_id}", headers=admin_headers, json=payload).status_code == 200


@pytest.mark.parametrize("field", ["role", "is_active", "display_name", "password", "unknown_field"])
def test_invalid_patch_is_rejected_before_database_write(client, admin_headers, admin_id, field):
    assert client.patch(f"/api/v1/users/{admin_id}", headers=admin_headers, json={field: None}).status_code == 422


def test_handover_to_another_active_admin_is_allowed(client, admin_headers, admin_id, db_session):
    second = add_admin(db_session)
    response = client.patch(f"/api/v1/users/{admin_id}", headers=admin_headers, json={"is_active": False})
    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.get(User, second).is_active
    assert client.get("/api/v1/users", headers=admin_headers).status_code == 403


@pytest.fixture
def account_engine(tmp_path, admin_id, db_session):
    second = add_admin(db_session)
    path = tmp_path / "accounts.db"
    raw = db_session.get_bind().raw_connection()
    try:
        with closing(sqlite3.connect(path)) as destination:
            raw.driver_connection.backup(destination)
    finally:
        raw.close()
    engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 0.1})
    yield engine, admin_id, second
    engine.dispose()


@pytest.mark.parametrize("field,value", [("role", "viewer"), ("is_active", False)])
def test_concurrent_changes_cannot_remove_both_admins(account_engine, monkeypatch, field, value):
    engine, first, second = account_engine
    entered, release = Event(), Event()
    original = UserRepository.update
    def paused_update(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return result
    monkeypatch.setattr(UserRepository, "update", staticmethod(paused_update))
    def demote(user_id):
        with Session(engine) as db:
            actor = db.get(User, user_id)
            UserService.update_user(db, user_id, UserUpdate(**{field: value}), actor=actor)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(demote, first)
        try:
            assert entered.wait(5)
            with pytest.raises(AccountWriteConflictError):
                demote(second)
        finally:
            release.set()
        future.result(timeout=5)
    with pytest.raises(LastActiveAdminError):
        demote(second)
    with Session(engine) as observer:
        assert observer.scalar(select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))) == 1
        assert observer.get(User, second).role == "admin" and observer.get(User, second).is_active


@pytest.mark.parametrize("operation", ["create", "update"])
def test_stale_revoked_actor_cannot_change_accounts(account_engine, operation):
    engine, first, second = account_engine
    with Session(engine, expire_on_commit=False) as stale:
        actor = stale.get(User, first)
        stale.commit()
        with Session(engine) as db:
            UserService.update_user(db, first, UserUpdate(role="viewer"), actor=db.get(User, second))
        assert actor.role == "admin"
        with pytest.raises(AccountAuthorizationError):
            if operation == "create":
                UserService.create_user(stale, UserCreate(username="forbidden", display_name="No", password="StrongPassword123"), actor=actor)
            else:
                UserService.update_user(stale, second, UserUpdate(display_name="forbidden"), actor=actor)
        assert not stale.in_transaction()
    with Session(engine) as observer:
        assert observer.scalar(select(func.count()).select_from(User)) == 2
        assert observer.get(User, second).display_name != "forbidden"


def test_commit_failure_rolls_back_admin_change_and_releases_lock(account_engine, monkeypatch):
    engine, first, second = account_engine
    with Session(engine) as db:
        def fail_commit():
            raise RuntimeError("injected commit failure")
        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="injected"):
            UserService.update_user(db, first, UserUpdate(is_active=False))
        assert not db.in_transaction()
    with Session(engine) as db:
        assert db.get(User, first).is_active
        UserService.update_user(db, second, UserUpdate(is_active=False))
        assert db.get(User, first).is_active
