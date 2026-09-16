from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from threading import Event

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import backend.app.services.auth as auth_module
from backend.app.core.config import settings
from backend.app.core.security import verify_password
from backend.app.models.audit_log import AuditLog
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.services.auth import (
    AuthenticationTemporarilyUnavailableError,
    AuthService,
    DUMMY_PASSWORD_HASH,
    GENERIC_LOGIN_FAILURE_MESSAGE,
    InvalidCredentialsError,
)
from backend.app.schemas.user import UserUpdate
from backend.app.services.user import UserService
from backend.tests.test_last_active_admin import account_engine, admin_id


def create_user(
    client,
    admin_headers,
    *,
    username="throttled_user",
    password="StrongPassword123",
):
    response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": username,
            "display_name": "Login Throttle Test",
            "password": password,
            "role": "viewer",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def login(client, username, password):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )


def test_unknown_user_still_runs_password_verifier(client, monkeypatch):
    calls = []

    def capture_verify(password, password_hash):
        calls.append((password, password_hash))
        return False

    monkeypatch.setattr(auth_module, "verify_password", capture_verify)
    response = login(client, "unknown_user", "NotARealPassword")

    assert response.status_code == 401
    assert response.json() == {"detail": GENERIC_LOGIN_FAILURE_MESSAGE}
    assert calls == [("NotARealPassword", DUMMY_PASSWORD_HASH)]


def test_wrong_unknown_inactive_and_locked_responses_are_indistinguishable(
    client,
    admin_headers,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 2)
    active_id = create_user(client, admin_headers, username="active_login")
    inactive_id = create_user(client, admin_headers, username="inactive_login")
    assert client.patch(
        f"/api/v1/users/{inactive_id}",
        headers=admin_headers,
        json={"is_active": False},
    ).status_code == 200

    wrong = login(client, "active_login", "WrongPassword123")
    unknown = login(client, "missing_login", "WrongPassword123")
    inactive = login(client, "inactive_login", "StrongPassword123")
    assert login(client, "active_login", "WrongPassword123").status_code == 401
    locked = login(client, "active_login", "StrongPassword123")

    responses = [wrong, unknown, inactive, locked]
    assert {response.status_code for response in responses} == {401}
    assert {json.dumps(response.json(), sort_keys=True) for response in responses} == {
        json.dumps({"detail": GENERIC_LOGIN_FAILURE_MESSAGE}, sort_keys=True)
    }
    db_session.expire_all()
    assert db_session.get(User, active_id).login_locked_until is not None


def test_threshold_persists_lock_and_bounds_audit_growth(
    client,
    admin_headers,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 3)
    user_id = create_user(client, admin_headers)
    wrong_password = "DefinitelyWrong123"

    for _ in range(3):
        assert login(client, "throttled_user", wrong_password).status_code == 401

    db_session.expire_all()
    user = db_session.get(User, user_id)
    assert user.failed_login_count == 3
    assert user.failed_login_window_started_at is not None
    assert user.login_locked_until is not None

    failures = list(db_session.scalars(
        select(AuditLog)
        .where(
            AuditLog.entity_id == user_id,
            AuditLog.event_type == "login_failed",
        )
        .order_by(AuditLog.created_at, AuditLog.id)
    ))
    assert [event.event_data["failure_count"] for event in failures] == [1, 2, 3]
    assert [event.event_data["account_locked"] for event in failures] == [
        False,
        False,
        True,
    ]

    # Correct credentials remain rejected during the lock, but repeated calls
    # neither extend it nor create unbounded audit rows.
    original_lock = user.login_locked_until
    assert login(
        client,
        "throttled_user",
        "StrongPassword123",
    ).status_code == 401
    db_session.expire_all()
    user = db_session.get(User, user_id)
    assert user.login_locked_until == original_lock
    assert db_session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(
            AuditLog.entity_id == user_id,
            AuditLog.event_type == "login_failed",
        )
    ) == 3
    serialized = json.dumps([event.event_data for event in failures])
    assert wrong_password not in serialized
    assert user.password_hash not in serialized


def test_success_before_threshold_clears_state_and_records_recovery(
    client,
    admin_headers,
    db_session,
):
    user_id = create_user(client, admin_headers)
    for _ in range(2):
        assert login(
            client,
            "throttled_user",
            "DefinitelyWrong123",
        ).status_code == 401

    assert login(
        client,
        "throttled_user",
        "StrongPassword123",
    ).status_code == 200
    db_session.expire_all()
    user = db_session.get(User, user_id)
    assert user.failed_login_count == 0
    assert user.failed_login_window_started_at is None
    assert user.login_locked_until is None

    recovery = db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_id == user_id,
            AuditLog.event_type == "login_throttle_cleared",
        )
    )
    assert recovery.event_data == {
        "schema_version": 1,
        "reason": "successful_login",
        "previous_failure_count": 2,
        "previously_locked": False,
    }


def test_failure_window_and_lock_expiry_use_fresh_windows(
    client,
    admin_headers,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 2)
    monkeypatch.setattr(settings, "LOGIN_FAILURE_WINDOW_SECONDS", 60)
    monkeypatch.setattr(settings, "LOGIN_LOCKOUT_SECONDS", 30)
    user_id = create_user(client, admin_headers)
    started = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(InvalidCredentialsError):
        AuthService.authenticate(
            db_session,
            username="throttled_user",
            password="wrong-one",
            now=started,
        )
    with pytest.raises(InvalidCredentialsError):
        AuthService.authenticate(
            db_session,
            username="throttled_user",
            password="wrong-two",
            now=started + timedelta(seconds=61),
        )
    db_session.expire_all()
    user = db_session.get(User, user_id)
    assert user.failed_login_count == 1
    assert user.login_locked_until is None

    with pytest.raises(InvalidCredentialsError):
        AuthService.authenticate(
            db_session,
            username="throttled_user",
            password="wrong-three",
            now=started + timedelta(seconds=62),
        )
    db_session.expire_all()
    assert db_session.get(User, user_id).login_locked_until is not None

    authenticated = AuthService.authenticate(
        db_session,
        username="throttled_user",
        password="StrongPassword123",
        now=started + timedelta(seconds=93),
    )
    assert authenticated.id == user_id
    assert authenticated.failed_login_count == 0
    assert authenticated.login_locked_until is None


def test_admin_password_reset_clears_lock_in_same_audit_transaction(
    client,
    admin_headers,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 2)
    user_id = create_user(client, admin_headers)
    for _ in range(2):
        assert login(
            client,
            "throttled_user",
            "DefinitelyWrong123",
        ).status_code == 401

    response = client.patch(
        f"/api/v1/users/{user_id}",
        headers=admin_headers,
        json={"password": "RecoveredPassword456"},
    )
    assert response.status_code == 200
    db_session.expire_all()
    user = db_session.get(User, user_id)
    assert user.failed_login_count == 0
    assert user.failed_login_window_started_at is None
    assert user.login_locked_until is None

    update = db_session.scalar(
        select(AuditLog)
        .where(
            AuditLog.entity_id == user_id,
            AuditLog.event_type == "user_updated",
        )
        .order_by(AuditLog.created_at.desc())
    )
    assert update.event_data["password_reset"] is True
    assert update.event_data["login_throttle_cleared"] is True
    assert login(
        client,
        "throttled_user",
        "RecoveredPassword456",
    ).status_code == 200


def test_failed_audit_rolls_back_login_counter(
    client,
    admin_headers,
    db_session,
    monkeypatch,
):
    user_id = create_user(client, admin_headers)

    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected login audit failure")

    monkeypatch.setattr(AuditLogRepository, "create", staticmethod(fail_audit))
    with pytest.raises(RuntimeError, match="injected login audit failure"):
        AuthService.authenticate(
            db_session,
            username="throttled_user",
            password="DefinitelyWrong123",
        )
    assert not db_session.in_transaction()
    with Session(db_session.get_bind()) as observer:
        user = observer.get(User, user_id)
        assert user.failed_login_count == 0
        assert user.failed_login_window_started_at is None
        assert user.login_locked_until is None


def test_failed_recovery_audit_preserves_existing_throttle_state(
    client,
    admin_headers,
    db_session,
    monkeypatch,
):
    user_id = create_user(client, admin_headers)
    assert login(
        client,
        "throttled_user",
        "DefinitelyWrong123",
    ).status_code == 401

    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected recovery audit failure")

    monkeypatch.setattr(AuditLogRepository, "create", staticmethod(fail_audit))
    with pytest.raises(RuntimeError, match="injected recovery audit failure"):
        AuthService.authenticate(
            db_session,
            username="throttled_user",
            password="StrongPassword123",
        )
    assert not db_session.in_transaction()
    with Session(db_session.get_bind()) as observer:
        user = observer.get(User, user_id)
        assert user.failed_login_count == 1
        assert user.failed_login_window_started_at is not None


def test_failed_password_reset_audit_preserves_lock_and_password(
    client,
    admin_headers,
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 2)
    user_id = create_user(client, admin_headers)
    for _ in range(2):
        assert login(
            client,
            "throttled_user",
            "DefinitelyWrong123",
        ).status_code == 401
    db_session.expire_all()
    original = db_session.get(User, user_id)
    original_hash = original.password_hash
    original_lock = original.login_locked_until

    def fail_audit(*args, **kwargs):
        raise RuntimeError("injected password-reset audit failure")

    monkeypatch.setattr(AuditLogRepository, "create", staticmethod(fail_audit))
    with pytest.raises(RuntimeError, match="injected password-reset audit failure"):
        UserService.update_user(
            db_session,
            user_id,
            UserUpdate(password="ReplacementPassword456"),
        )
    assert not db_session.in_transaction()
    with Session(db_session.get_bind()) as observer:
        user = observer.get(User, user_id)
        assert user.password_hash == original_hash
        assert verify_password("StrongPassword123", user.password_hash)
        assert user.failed_login_count == 2
        assert user.login_locked_until == original_lock


def test_login_account_lock_is_bounded_and_released(account_engine, monkeypatch):
    engine, first_admin, second_admin = account_engine
    entered = Event()
    release = Event()
    original_verify = auth_module.verify_password

    def paused_verify(password, password_hash):
        entered.set()
        assert release.wait(5)
        return original_verify(password, password_hash)

    monkeypatch.setattr(auth_module, "verify_password", paused_verify)

    def authenticate(username, password):
        with Session(engine) as db:
            return AuthService.authenticate(
                db,
                username=username,
                password=password,
            ).id

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(authenticate, "testadmin", "StrongAdmin123")
        try:
            assert entered.wait(5)
            with pytest.raises(AuthenticationTemporarilyUnavailableError):
                authenticate("testadmin", "StrongAdmin123")
        finally:
            release.set()
        assert future.result(timeout=5) == first_admin

    monkeypatch.setattr(auth_module, "verify_password", original_verify)
    assert authenticate("secondadmin", "StrongPassword123") == second_admin


def test_temporary_account_contention_returns_retryable_503(
    client,
    monkeypatch,
):
    def unavailable(*args, **kwargs):
        raise AuthenticationTemporarilyUnavailableError(
            "Authentication is temporarily unavailable."
        )

    monkeypatch.setattr(AuthService, "authenticate", staticmethod(unavailable))
    response = login(client, "some_user", "some_password")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json() == {
        "detail": "Authentication is temporarily unavailable."
    }
