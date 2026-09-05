"""Exercise Alembic on disposable files, independently of metadata.create_all."""

from pathlib import Path
from datetime import datetime, timezone

import pytest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.patient import Patient
from backend.app.models.visit import Visit
from backend.app.models.treatment import Treatment
from backend.app.models.treatment_session import TreatmentSession
from backend.app.models.session_finalization import SessionFinalization


def test_upgrade_preserves_existing_data_and_round_trips(tmp_path, monkeypatch):
    database = tmp_path / "migration-test.db"
    url = f"sqlite:///{database}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    command.upgrade(config, "6adf71221e0b")

    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO patients "
                "(id, patient_code, first_name, last_name, is_active, created_at, updated_at) "
                "VALUES ('migration-patient', 'MIG-001', 'Test', 'Patient', 1, "
                "'2026-09-01 10:00:00', '2026-09-01 10:00:00')"
            ))

        command.upgrade(config, "head")
        inspector = inspect(engine)
        assert "treatment_session_components" in inspector.get_table_names()
        foreign_keys = inspector.get_foreign_keys("treatment_session_components")
        assert len(foreign_keys) == 3
        assert {fk["options"].get("ondelete") for fk in foreign_keys} == {"CASCADE", "RESTRICT"}
        assert len(inspector.get_check_constraints("treatment_session_components")) == 2
        assert len(inspector.get_unique_constraints("treatment_session_components")) == 1

        # This destructive downgrade is restricted to the disposable test file.
        command.downgrade(config, "6adf71221e0b")
        assert "treatment_session_components" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT patient_code FROM patients WHERE id = 'migration-patient'")) == "MIG-001"
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "b36e7f0a1d42"
    finally:
        engine.dispose()


def test_finalization_migration_preserves_legacy_sessions_and_refuses_evidence_loss(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'evidence-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "c68b24017654")
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            patient = Patient(patient_code="LEGACY", first_name="Test", last_name="Only")
            db.add(patient)
            db.flush()
            visit = Visit(patient_id=patient.id)
            db.add(visit)
            db.flush()
            treatment = Treatment(visit_id=visit.id, treatment_type="ACS")
            db.add(treatment)
            db.flush()
            session = TreatmentSession(treatment_id=treatment.id, session_number=1, status="completed",
                                       operational_status="completed", completed_at=datetime.now(timezone.utc))
            db.add(session)
            db.flush()
            session_id = session.id
            db.commit()
        command.upgrade(config, "head")
        inspector = inspect(engine)
        assert inspector.get_pk_constraint("session_finalizations")["constrained_columns"] == ["session_id"]
        assert inspector.get_foreign_keys("session_finalizations")[0]["options"]["ondelete"] == "RESTRICT"
        with Session(engine) as db:
            assert db.get(TreatmentSession, session_id).status == "completed"
            assert db.get(SessionFinalization, session_id) is None
        command.downgrade(config, "c68b24017654")  # empty evidence/revocation state is safe
        command.upgrade(config, "head")
        with Session(engine) as db:
            db.add(SessionFinalization(session_id=session_id, captured_at=datetime.now(timezone.utc),
                                       payload={"test_fixture": True}, sha256="0" * 64))
            db.commit()
        # First remove the empty revocation migration so the evidence guard is
        # the only downgrade step under test.
        command.downgrade(config, "a71d92cfe604")
        with pytest.raises(RuntimeError, match="evidence exists"):
            command.downgrade(config, "c68b24017654")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM session_finalizations")) == 1
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "a71d92cfe604"
    finally:
        engine.dispose()


def test_auth_version_migration_preserves_users_and_refuses_revocation_loss(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'auth-version-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "a71d92cfe604")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, role, is_active, created_at, updated_at) "
                "VALUES ('legacy-user', 'legacy', 'Legacy User', 'hash', 'viewer', 1, "
                "'2026-09-01 10:00:00', '2026-09-01 10:00:00')"
            ))
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT auth_version FROM users WHERE id = 'legacy-user'"
            )) == 0
        command.downgrade(config, "a71d92cfe604")
        assert "auth_version" not in {column["name"] for column in inspect(engine).get_columns("users")}
        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE users SET auth_version = 1 WHERE id = 'legacy-user'"
            ))
        with pytest.raises(RuntimeError, match="revoked account sessions exist"):
            command.downgrade(config, "a71d92cfe604")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "b36e7f0a1d42"
            assert connection.scalar(text(
                "SELECT auth_version FROM users WHERE id = 'legacy-user'"
            )) == 1
    finally:
        engine.dispose()
