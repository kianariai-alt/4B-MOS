"""Opt-in synthetic imaging integration against the disposable CI PostgreSQL service.

No schema setup or migration occurs in this module. CI prepares a fresh database;
the fixture refuses other hosts, database names and unmarked invocations before
truncating tables. The production application/session configuration is unchanged.
"""

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytest.importorskip("backend.app.services.clinical_integration.service")

from backend.app.api.routes.clinical_integration import get_integration_adapters
from backend.app.db.clinical_record_transactions import ClinicalRecordWriteConflictError
from backend.app.db.session import get_db
from backend.app.imaging_intelligence.integration import GatedImagingRecordAdapter
from backend.app.main import app
from backend.app.models.audit_log import AuditLog
from backend.app.models.clinical_integration import ClinicalIntegrationRun
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.clinical_integration import IntegrationRunCreate
from backend.app.services.clinical_integration.adapters import local_adapters
from backend.app.services.clinical_integration.service import ClinicalIntegrationService
from backend.tests.test_imaging_integration_freshness import (
    build_synthetic_gate, create_run, enable_preview, inputs, physician, visit,
    test_changed_sidecar_invalidates_saved_run_and_blocks_review as assert_freshness,
)
from backend.tests.test_postgresql_integration import postgresql_engine, _truncate_application_tables


pytestmark = [
    pytest.mark.skipif(os.getenv("MOS_SYNTHETIC_POSTGRESQL_ONLY") != "1",
                       reason="Explicit disposable imaging PostgreSQL CI marker is required."),
    pytest.mark.usefixtures("authenticated_admin"),
]


@pytest.fixture(autouse=True)
def reset_database(postgresql_engine):
    # Override conftest's SQLite fixture: every request in these tests must use PG.
    url = postgresql_engine.url
    if (os.getenv("ENVIRONMENT") != "test" or url.host != "127.0.0.1"
            or url.database != "mos_imaging_ci" or url.port != 5432):
        pytest.fail("Only the dedicated loopback synthetic CI database is allowed.")
    _truncate_application_tables(postgresql_engine)

    def database():
        with Session(postgresql_engine, autoflush=False, expire_on_commit=False) as db:
            yield db

    app.dependency_overrides[get_db] = database
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        _truncate_application_tables(postgresql_engine)


@pytest.fixture
def db_session(postgresql_engine, reset_database):
    with Session(postgresql_engine, autoflush=False, expire_on_commit=False) as db:
        yield db


@pytest.mark.parametrize("dependency", ["study", "clinical", "binding"])
def test_postgresql_sidecar_freshness_and_review(
        client, db_session, visit, inputs, physician, tmp_path, dependency):
    assert db_session.bind.dialect.name == "postgresql"
    assert_freshness(client, db_session, visit, inputs, physician, tmp_path, dependency)


@pytest.fixture
def imaging_gate(db_session, visit, inputs, tmp_path):
    values, context = build_synthetic_gate(db_session, visit["id"], tmp_path)
    adapters = local_adapters() | {"imaging": GatedImagingRecordAdapter(**values)}
    app.dependency_overrides[get_integration_adapters] = lambda: adapters
    return context, adapters


def test_postgresql_concurrent_same_request_has_one_run_and_one_audit(
        postgresql_engine, db_session, visit, imaging_gate):
    context, adapters = imaging_gate
    actor_id = db_session.scalar(select(User.id).where(User.username == "integration_physician"))
    assert actor_id is not None
    payload = IntegrationRunCreate(request_key="synthetic-concurrent-imaging",
                                   expected_clinical_context_sha256=context.clinical_context_sha256)
    db_session.rollback()
    barrier = Barrier(2)

    def create(*, synchronize=False):
        with Session(postgresql_engine) as db:
            actor = db.get(User, actor_id)
            if synchronize:
                barrier.wait(timeout=10)
            try:
                return ClinicalIntegrationService.create(db, visit["id"], payload, actor=actor, adapters=adapters)
            except ClinicalRecordWriteConflictError:
                # A bounded lock conflict is a permitted response; retry only
                # after both concurrent calls have completed, without a sleep.
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        calls = [pool.submit(create, synchronize=True) for _ in range(2)]
        results = [call.result(timeout=20) for call in calls]
    assert any(result is not None for result in results)
    results = [result if result is not None else create() for result in results]
    assert all(result is not None and result.freshness == "current" for result in results)
    assert results[0].id == results[1].id
    assert results[0].result_sha256 == results[1].result_sha256
    assert results[0].result.workflow_state == "awaiting_physician_review"
    with Session(postgresql_engine) as db:
        assert db.scalar(select(func.count()).select_from(ClinicalIntegrationRun)) == 1
        assert db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_type == "clinical_integration",
            AuditLog.event_type == "integration_run_created")) == 1


def test_postgresql_audit_failure_rolls_back_imaging_run(
        client, postgresql_engine, db_session, visit, imaging_gate, monkeypatch):
    original = AuditLogRepository.create

    def fail_integration_audit(*args, **kwargs):
        if kwargs.get("entity_type") == "clinical_integration":
            raise RuntimeError("Synthetic imaging audit failure.")
        return original(*args, **kwargs)

    monkeypatch.setattr(AuditLogRepository, "create", fail_integration_audit)
    db_session.rollback()
    with pytest.raises(RuntimeError, match="^Synthetic imaging audit failure[.]$"):
        create_run(client, visit)
    with Session(postgresql_engine) as db:
        assert db.scalar(select(func.count()).select_from(ClinicalIntegrationRun)) == 0
        assert db.scalar(select(func.count()).select_from(AuditLog).where(
            AuditLog.entity_type == "clinical_integration")) == 0
