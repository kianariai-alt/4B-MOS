"""Disposable PostgreSQL migration, locking and concurrency integration tests.

These tests are skipped during the normal SQLite suite. GitHub Actions supplies
``TEST_POSTGRESQL_URL`` and points the application's engine at an ephemeral
PostgreSQL service that has already been upgraded with Alembic.
"""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier, Event
import uuid

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

import backend.app.models  # noqa: F401 - register every mapped table
from backend.app.core.config import settings
from backend.app.core.database_revision import EXPECTED_DATABASE_REVISION
from backend.app.db.account_transactions import (
    AccountWriteConflictError,
    lock_accounts,
)
from backend.app.db.base import Base
from backend.app.db.session import engine as application_engine
from backend.app.db.transactions import ClinicalWriteConflictError, atomic_write
from backend.app.models.audit_log import AuditLog
from backend.app.models.patient import Patient
from backend.app.models.session_amendment import SessionAmendment
from backend.app.models.treatment import Treatment
from backend.app.models.treatment_session import TreatmentSession
from backend.app.models.user import User
from backend.app.models.visit import Visit
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.user import UserRepository
from backend.app.schemas.session_amendment import SessionAmendmentCreate
from backend.app.schemas.treatment_session import TreatmentSessionUpdate
from backend.app.schemas.user import UserCreate, UserUpdate
from backend.app.services.auth import (
    AuthenticationTemporarilyUnavailableError,
    AuthService,
    InvalidCredentialsError,
)
from backend.app.services.session_amendment import SessionAmendmentService
from backend.app.services.session_workflow import SessionWorkflowService
from backend.app.services.treatment_session import TreatmentSessionService
from backend.app.services.user import LastActiveAdminError, UserService


POSTGRESQL_URL = os.getenv("TEST_POSTGRESQL_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRESQL_URL,
    reason="TEST_POSTGRESQL_URL is required for PostgreSQL integration tests.",
)


@pytest.fixture(scope="module")
def postgresql_engine():
    test_url = make_url(POSTGRESQL_URL)
    if application_engine.dialect.name != "postgresql":
        pytest.fail(
            "TEST_POSTGRESQL_URL is set but DATABASE_URL did not configure "
            "the application engine for PostgreSQL."
        )
    if application_engine.url != test_url:
        pytest.fail(
            "DATABASE_URL and TEST_POSTGRESQL_URL must identify the same "
            "disposable PostgreSQL database."
        )
    if not test_url.database or not test_url.database.endswith(("_ci", "_test")):
        pytest.fail(
            "PostgreSQL integration tests require a database name ending "
            "in '_ci' or '_test'."
        )
    yield application_engine
    application_engine.dispose()


def _truncate_application_tables(engine) -> None:
    table_names = [table.name for table in Base.metadata.sorted_tables]
    with engine.begin() as connection:
        quote = connection.dialect.identifier_preparer.quote
        targets = ", ".join(quote(name) for name in table_names)
        connection.execute(
            text(f"TRUNCATE TABLE {targets} RESTART IDENTITY CASCADE")
        )


@pytest.fixture(autouse=True)
def clean_postgresql(postgresql_engine):
    _truncate_application_tables(postgresql_engine)
    yield
    _truncate_application_tables(postgresql_engine)


def _id() -> str:
    return str(uuid.uuid4())


def _seed_clinical_context(engine, *, treatment_count: int = 2) -> dict:
    patient_id = _id()
    visit_id = _id()
    treatment_ids = [_id() for _ in range(treatment_count)]
    session_ids = [_id() for _ in range(treatment_count)]
    admin_ids = [_id(), _id()]

    with Session(engine) as db:
        db.add(
            Patient(
                id=patient_id,
                patient_code=f"PG-{uuid.uuid4().hex[:12]}",
                first_name="PostgreSQL",
                last_name="Integration",
            )
        )
        db.add(Visit(id=visit_id, patient_id=patient_id))
        for number, (treatment_id, session_id) in enumerate(
            zip(treatment_ids, session_ids, strict=True),
            start=1,
        ):
            db.add(
                Treatment(
                    id=treatment_id,
                    visit_id=visit_id,
                    treatment_type="PRP",
                    session_number=number,
                )
            )
            db.add(
                TreatmentSession(
                    id=session_id,
                    treatment_id=treatment_id,
                    session_number=1,
                )
            )
        for number, admin_id in enumerate(admin_ids, start=1):
            db.add(
                User(
                    id=admin_id,
                    username=f"postgres_admin_{number}",
                    display_name=f"PostgreSQL Administrator {number}",
                    password_hash="integration-test-password-hash-not-for-login",
                    role="admin",
                )
            )
        db.commit()

    return {
        "patient_id": patient_id,
        "visit_id": visit_id,
        "treatment_ids": treatment_ids,
        "session_ids": session_ids,
        "admin_ids": admin_ids,
    }


def _sqlstate(conflict: Exception) -> str | None:
    database_error = conflict.__cause__
    original = getattr(database_error, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(
        original,
        "pgcode",
        None,
    )


def _amendment_payload(statement: str) -> SessionAmendmentCreate:
    return SessionAmendmentCreate(
        amendment_type="correction",
        reason_code="data_entry_error",
        reason_detail="The original note contained a transcription error.",
        statement=statement,
        target_reference="session.notes",
    )


def _finalize(engine, session_id: str, actor_id: str) -> None:
    with Session(engine) as db:
        actor = db.get(User, actor_id)
        for target in ("checked_in", "ready", "in_treatment", "completed"):
            SessionWorkflowService.transition(
                db,
                session_id,
                target,
                actor=actor,
            )


def test_postgresql_schema_revision_is_ready_and_lock_wait_is_bounded(
    postgresql_engine,
):
    with postgresql_engine.connect() as connection:
        assert connection.get_isolation_level() == "READ COMMITTED"
        lock_timeout = connection.execute(
            text(
                "SELECT CAST(setting AS integer) FROM pg_settings "
                "WHERE name = 'lock_timeout'"
            )
        ).scalar_one()
        assert lock_timeout == settings.DATABASE_LOCK_TIMEOUT_MS
        assert connection.scalar(
            text("SELECT version_num FROM alembic_version")
        ) == EXPECTED_DATABASE_REVISION
        assert set(Base.metadata.tables) <= set(inspect(connection).get_table_names())


def test_parent_lock_times_out_for_same_treatment_but_not_another(
    postgresql_engine,
    monkeypatch,
):
    context = _seed_clinical_context(postgresql_engine)
    first_session, second_session = context["session_ids"]
    actor_id = context["admin_ids"][0]
    entered = Event()
    release = Event()
    original_audit = AuditLogRepository.create

    def pause_first_session_audit(*args, **kwargs):
        result = original_audit(*args, **kwargs)
        if (
            kwargs.get("entity_id") == first_session
            and kwargs.get("event_type") == "session_updated"
        ):
            entered.set()
            assert release.wait(10), "test failed to release PostgreSQL writer"
        return result

    monkeypatch.setattr(
        AuditLogRepository,
        "create",
        staticmethod(pause_first_session_audit),
    )

    def update_notes(session_id: str, notes: str) -> None:
        with Session(postgresql_engine) as db:
            actor = db.get(User, actor_id)
            TreatmentSessionService.update_session(
                db,
                session_id,
                TreatmentSessionUpdate(notes=notes),
                actor=actor,
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(update_notes, first_session, "leader")
        try:
            assert entered.wait(10), "PostgreSQL writer did not reach audit"
            with pytest.raises(ClinicalWriteConflictError) as conflict:
                update_notes(first_session, "must roll back")
            assert _sqlstate(conflict.value) == "55P03"

            # PostgreSQL locks only the selected treatment row. This command
            # must remain independent while the first treatment is locked.
            update_notes(second_session, "independent treatment")
        finally:
            release.set()
        future.result(timeout=10)

    with Session(postgresql_engine) as observer:
        assert observer.get(TreatmentSession, first_session).notes == "leader"
        assert (
            observer.get(TreatmentSession, second_session).notes
            == "independent treatment"
        )
        failed_audits = observer.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == first_session,
                AuditLog.event_type == "session_updated",
            )
        ).all()
        assert len(failed_audits) == 1


def test_postgresql_deadlock_is_mapped_to_controlled_conflict(postgresql_engine):
    context = _seed_clinical_context(postgresql_engine)
    first_treatment, second_treatment = context["treatment_ids"]
    rendezvous = Barrier(2)

    @atomic_write
    def lock_in_opposite_order(
        db: Session,
        treatment_id: str,
        second_treatment_id: str,
    ) -> None:
        # The decorator already owns the first parent row. Disable the regular
        # lock timeout for this transaction so PostgreSQL's deadlock detector,
        # rather than the timeout, resolves the opposite-order wait.
        db.execute(text("SET LOCAL lock_timeout = '0'"))
        rendezvous.wait(timeout=10)
        db.execute(
            select(Treatment.id)
            .where(Treatment.id == second_treatment_id)
            .with_for_update()
        )

    def run(first: str, second: str) -> tuple[str, str | None]:
        try:
            with Session(postgresql_engine) as db:
                lock_in_opposite_order(db, first, second)
        except ClinicalWriteConflictError as conflict:
            return "conflict", _sqlstate(conflict)
        return "committed", None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (
            pool.submit(run, first_treatment, second_treatment),
            pool.submit(run, second_treatment, first_treatment),
        )
        outcomes = [future.result(timeout=15) for future in futures]

    assert sorted(status for status, _ in outcomes) == ["committed", "conflict"]
    assert [state for status, state in outcomes if status == "conflict"] == [
        "40P01"
    ]


def test_account_table_lock_preserves_last_active_admin(postgresql_engine, monkeypatch):
    context = _seed_clinical_context(postgresql_engine, treatment_count=1)
    first_admin, second_admin = context["admin_ids"]
    entered = Event()
    release = Event()
    original_update = UserRepository.update

    def pause_first_demotion(db, user, update_data, *, commit=True):
        result = original_update(
            db,
            user,
            update_data,
            commit=commit,
        )
        if user.id == first_admin:
            entered.set()
            assert release.wait(10), "test failed to release account writer"
        return result

    monkeypatch.setattr(
        UserRepository,
        "update",
        staticmethod(pause_first_demotion),
    )

    def demote(user_id: str) -> None:
        with Session(postgresql_engine) as db:
            actor = db.get(User, user_id)
            UserService.update_user(
                db,
                user_id,
                UserUpdate(role="viewer"),
                actor=actor,
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(demote, first_admin)
        try:
            assert entered.wait(10), "account writer did not acquire PostgreSQL lock"
            with pytest.raises(AccountWriteConflictError) as conflict:
                demote(second_admin)
            assert _sqlstate(conflict.value) == "55P03"
        finally:
            release.set()
        future.result(timeout=10)

    monkeypatch.setattr(
        UserRepository,
        "update",
        staticmethod(original_update),
    )
    with pytest.raises(LastActiveAdminError):
        demote(second_admin)

    with Session(postgresql_engine) as observer:
        active_admins = observer.scalars(
            select(User).where(User.role == "admin", User.is_active.is_(True))
        ).all()
        assert [user.id for user in active_admins] == [second_admin]


def test_account_lock_rejects_repeatable_read(postgresql_engine):
    repeatable_read_engine = postgresql_engine.execution_options(
        isolation_level="REPEATABLE READ"
    )
    with Session(repeatable_read_engine) as db:
        with pytest.raises(
            AccountWriteConflictError,
            match="requires READ COMMITTED",
        ):
            lock_accounts(db)
        db.rollback()


def test_postgresql_login_failures_are_serialized_and_persistent(
    postgresql_engine,
    monkeypatch,
):
    context = _seed_clinical_context(postgresql_engine, treatment_count=1)
    actor_id = context["admin_ids"][0]
    with Session(postgresql_engine) as db:
        target = UserService.create_user(
            db,
            UserCreate(
                username="postgres_login_target",
                display_name="PostgreSQL Login Target",
                password="StrongPassword123",
                role="viewer",
            ),
            actor=db.get(User, actor_id),
        )
        target_id = target.id
        independent = UserService.create_user(
            db,
            UserCreate(
                username="postgres_independent_login",
                display_name="Independent PostgreSQL Login",
                password="IndependentPassword123",
                role="viewer",
            ),
            actor=db.get(User, actor_id),
        )
        independent_id = independent.id

    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 2)
    entered = Event()
    release = Event()
    original_audit = AuditLogRepository.create

    def pause_first_failure(*args, **kwargs):
        result = original_audit(*args, **kwargs)
        if (
            kwargs.get("entity_id") == target_id
            and kwargs.get("event_type") == "login_failed"
            and not entered.is_set()
        ):
            entered.set()
            assert release.wait(10), "test failed to release login writer"
        return result

    monkeypatch.setattr(
        AuditLogRepository,
        "create",
        staticmethod(pause_first_failure),
    )

    def fail_login() -> None:
        with Session(postgresql_engine) as db:
            with pytest.raises(InvalidCredentialsError):
                AuthService.authenticate(
                    db,
                    username="postgres_login_target",
                    password="DefinitelyWrong123",
                )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fail_login)
        try:
            assert entered.wait(10), "login writer did not reach audit"
            # Account-bound PostgreSQL locks must not block an unrelated login.
            with Session(postgresql_engine) as db:
                assert AuthService.authenticate(
                    db,
                    username="postgres_independent_login",
                    password="IndependentPassword123",
                ).id == independent_id
            with Session(postgresql_engine) as db:
                with pytest.raises(
                    AuthenticationTemporarilyUnavailableError
                ) as conflict:
                    AuthService.authenticate(
                        db,
                        username="postgres_login_target",
                        password="DefinitelyWrong123",
                    )
                assert _sqlstate(conflict.value) == "55P03"
        finally:
            release.set()
        future.result(timeout=10)

    monkeypatch.setattr(
        AuditLogRepository,
        "create",
        staticmethod(original_audit),
    )
    fail_login()

    with Session(postgresql_engine) as observer:
        target = observer.get(User, target_id)
        assert target.failed_login_count == 2
        assert target.login_locked_until is not None
        failures = observer.scalars(
            select(AuditLog).where(
                AuditLog.entity_id == target_id,
                AuditLog.event_type == "login_failed",
            )
        ).all()
        assert len(failures) == 2


def test_concurrent_amendments_keep_stable_postgresql_sequence(
    postgresql_engine,
    monkeypatch,
):
    context = _seed_clinical_context(postgresql_engine, treatment_count=1)
    session_id = context["session_ids"][0]
    actor_id = context["admin_ids"][0]
    _finalize(postgresql_engine, session_id, actor_id)
    entered = Event()
    release = Event()
    original_audit = AuditLogRepository.create

    def pause_amendment_audit(*args, **kwargs):
        result = original_audit(*args, **kwargs)
        if kwargs.get("event_type") == "session_amendment_created":
            entered.set()
            assert release.wait(10), "test failed to release amendment writer"
        return result

    monkeypatch.setattr(
        AuditLogRepository,
        "create",
        staticmethod(pause_amendment_audit),
    )

    def create_amendment(statement: str) -> None:
        with Session(postgresql_engine) as db:
            actor = db.get(User, actor_id)
            SessionAmendmentService.create(
                db,
                session_id,
                _amendment_payload(statement),
                actor=actor,
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(create_amendment, "First PostgreSQL amendment.")
        try:
            assert entered.wait(10), "amendment writer did not reach audit"
            with pytest.raises(ClinicalWriteConflictError) as conflict:
                create_amendment("Conflicting amendment must roll back.")
            assert _sqlstate(conflict.value) == "55P03"
        finally:
            release.set()
        future.result(timeout=10)

    monkeypatch.setattr(
        AuditLogRepository,
        "create",
        staticmethod(original_audit),
    )
    create_amendment("Second serialized PostgreSQL amendment.")

    with Session(postgresql_engine) as observer:
        amendments = observer.scalars(
            select(SessionAmendment)
            .where(SessionAmendment.session_id == session_id)
            .order_by(SessionAmendment.sequence)
        ).all()
        assert [amendment.sequence for amendment in amendments] == [1, 2]
        assert [amendment.payload["statement"] for amendment in amendments] == [
            "First PostgreSQL amendment.",
            "Second serialized PostgreSQL amendment.",
        ]
