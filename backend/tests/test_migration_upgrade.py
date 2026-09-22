"""Exercise Alembic on disposable files, independently of metadata.create_all."""

from pathlib import Path
from datetime import datetime, timezone
import uuid

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
from backend.app.models.session_amendment import (
    SessionAmendment,
    SessionAmendmentReview,
)


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
        assert "session_amendments" in inspector.get_table_names()
        assert "session_amendment_reviews" in inspector.get_table_names()
        assert inspector.get_foreign_keys("session_amendments")[0]["options"]["ondelete"] == "RESTRICT"
        assert inspector.get_foreign_keys("session_amendment_reviews")[0]["options"]["ondelete"] == "RESTRICT"

        # This destructive downgrade is restricted to the disposable test file.
        command.downgrade(config, "6adf71221e0b")
        assert "treatment_session_components" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT patient_code FROM patients WHERE id = 'migration-patient'")) == "MIG-001"
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "b7d4e6f8c230"
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
            treatment_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            db.execute(
                text(
                    "INSERT INTO treatments "
                    "(id, visit_id, treatment_type, status, session_number, "
                    "created_at, updated_at) "
                    "VALUES (:id, :visit_id, 'ACS', 'planned', 1, "
                    ":created_at, :updated_at)"
                ),
                {
                    "id": treatment_id,
                    "visit_id": visit.id,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            session = TreatmentSession(treatment_id=treatment_id, session_number=1, status="completed",
                                       operational_status="completed", completed_at=now)
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


def test_amendment_migration_refuses_loss_of_pending_or_reviewed_history(
    tmp_path,
    monkeypatch,
):
    url = f"sqlite:///{tmp_path / 'amendment-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        now = datetime.now(timezone.utc)
        with Session(engine) as db:
            patient = Patient(
                patient_code="AMEND-MIG",
                first_name="Amendment",
                last_name="Migration",
            )
            db.add(patient)
            db.flush()
            visit = Visit(patient_id=patient.id)
            db.add(visit)
            db.flush()
            treatment = Treatment(visit_id=visit.id, treatment_type="ACS")
            db.add(treatment)
            db.flush()
            session = TreatmentSession(
                treatment_id=treatment.id,
                session_number=1,
                status="completed",
                operational_status="completed",
                completed_at=now,
            )
            db.add(session)
            db.flush()
            db.add(
                SessionFinalization(
                    session_id=session.id,
                    captured_at=now,
                    payload={"migration_fixture": True},
                    sha256="0" * 64,
                )
            )
            db.flush()
            amendment = SessionAmendment(
                session_id=session.id,
                sequence=1,
                created_at=now,
                payload={"migration_fixture": True},
                sha256="1" * 64,
            )
            db.add(amendment)
            db.flush()
            db.add(
                SessionAmendmentReview(
                    amendment_id=amendment.id,
                    decision="approved",
                    reviewed_at=now,
                    payload={"migration_fixture": True},
                    sha256="2" * 64,
                )
            )
            db.commit()

        with pytest.raises(RuntimeError, match="amendment history exists"):
            command.downgrade(config, "b36e7f0a1d42")
        inspector = inspect(engine)
        assert "session_amendments" in inspector.get_table_names()
        assert "session_amendment_reviews" in inspector.get_table_names()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM session_amendments")) == 1
            assert connection.scalar(text("SELECT count(*) FROM session_amendment_reviews")) == 1
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "d9a4c7e2f1b6"
    finally:
        engine.dispose()


def test_login_throttle_migration_defaults_and_refuses_security_state_loss(
    tmp_path,
    monkeypatch,
):
    url = f"sqlite:///{tmp_path / 'login-throttle-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "d9a4c7e2f1b6")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, role, is_active, "
                "auth_version, created_at, updated_at) "
                "VALUES ('legacy-login-user', 'legacy_login', 'Legacy Login', "
                "'hash', 'viewer', 1, 0, "
                "'2026-09-01 10:00:00', '2026-09-01 10:00:00')"
            ))

        command.upgrade(config, "head")
        with engine.connect() as connection:
            row = connection.execute(text(
                "SELECT failed_login_count, failed_login_window_started_at, "
                "login_locked_until FROM users WHERE id = 'legacy-login-user'"
            )).one()
            assert tuple(row) == (0, None, None)
            assert connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            )) == "b7d4e6f8c230"

        command.downgrade(config, "d9a4c7e2f1b6")
        columns = {column["name"] for column in inspect(engine).get_columns("users")}
        assert "failed_login_count" not in columns

        command.upgrade(config, "head")
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE users SET failed_login_count = 1, "
                "failed_login_window_started_at = '2026-09-16 12:00:00' "
                "WHERE id = 'legacy-login-user'"
            ))
        with pytest.raises(RuntimeError, match="login throttling state exists"):
            command.downgrade(config, "d9a4c7e2f1b6")
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            )) == "e21f6a9c3b40"
            assert connection.scalar(text(
                "SELECT failed_login_count FROM users "
                "WHERE id = 'legacy-login-user'"
            )) == 1
    finally:
        engine.dispose()


def test_medical_knowledge_migration_refuses_registry_data_loss(
    tmp_path,
    monkeypatch,
):
    url = f"sqlite:///{tmp_path / 'medical-knowledge-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert "medical_knowledge_facts" in inspector.get_table_names()
        assert "medical_knowledge_sources" in inspector.get_table_names()
        assert len(inspector.get_foreign_keys("medical_knowledge_facts")) == 3
        assert (
            inspector.get_foreign_keys("medical_knowledge_sources")[0][
                "options"
            ]["ondelete"]
            == "CASCADE"
        )

        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, role, is_active, "
                "auth_version, failed_login_count, created_at, updated_at) "
                "VALUES ('knowledge-user', 'knowledge_user', 'Knowledge User', "
                "'hash', 'admin', 1, 0, 0, "
                "'2026-09-19 10:00:00', '2026-09-19 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO medical_knowledge_facts "
                "(id, fact_key, version, title, statement, clinical_domain, "
                "contraindications, evidence_grade, status, content_sha256, "
                "created_by_user_id, row_version, created_at, updated_at) "
                "VALUES ('knowledge-fact', 'MIG-FACT-001', 1, 'Migration fact', "
                "'Synthetic migration statement with sufficient fixture text.', "
                "'migration', '[]', 'ungraded', 'draft', '" + "0" * 64 + "', "
                "'knowledge-user', 1, "
                "'2026-09-19 10:00:00', '2026-09-19 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO medical_knowledge_sources "
                "(id, fact_id, sort_order, source_type, title, citation, "
                "accessed_at, created_at) "
                "VALUES ('knowledge-source', 'knowledge-fact', 1, 'other', "
                "'Synthetic source', 'Migration-only fixture', "
                "'2026-09-19', '2026-09-19 10:00:00')"
            ))

        with pytest.raises(RuntimeError, match="registry contains data"):
            command.downgrade(config, "e21f6a9c3b40")
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            )) == "f4b14c2d9a01"
            assert connection.scalar(text(
                "SELECT count(*) FROM medical_knowledge_facts"
            )) == 1
            assert connection.scalar(text(
                "SELECT count(*) FROM medical_knowledge_sources"
            )) == 1
    finally:
        engine.dispose()


def test_structured_clinical_context_migration_refuses_patient_data_loss(
    tmp_path,
    monkeypatch,
):
    url = f"sqlite:///{tmp_path / 'structured-context-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert {
            "clinical_intakes",
            "paraclinical_reports",
            "paraclinical_observations",
        } <= set(inspector.get_table_names())
        assert len(inspector.get_foreign_keys("clinical_intakes")) == 5
        assert len(inspector.get_foreign_keys("paraclinical_reports")) == 5
        assert (
            inspector.get_foreign_keys("paraclinical_observations")[0][
                "options"
            ]["ondelete"]
            == "CASCADE"
        )
        observation_checks = {
            check["name"]
            for check in inspector.get_check_constraints(
                "paraclinical_observations"
            )
        }
        assert "ck_paraclinical_observation_value" in observation_checks
        assert (
            "ck_paraclinical_observation_quantity_metadata"
            in observation_checks
        )

        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, role, is_active, "
                "auth_version, failed_login_count, created_at, updated_at) "
                "VALUES ('context-user', 'context_user', 'Context User', "
                "'hash', 'physician', 1, 0, 0, "
                "'2026-09-20 10:00:00', '2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO patients "
                "(id, patient_code, first_name, last_name, is_active, "
                "created_at, updated_at) VALUES "
                "('context-patient', 'CTX-MIG-001', 'Context', 'Patient', 1, "
                "'2026-09-20 10:00:00', '2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO visits "
                "(id, patient_id, visit_date, status, created_at, updated_at) "
                "VALUES ('context-visit', 'context-patient', "
                "'2026-09-20 10:00:00', 'open', "
                "'2026-09-20 10:00:00', '2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO clinical_intakes "
                "(id, visit_id, version, status, chief_complaint, "
                "history_present_illness, functional_limitations, "
                "relevant_history, current_medications, allergies, red_flags, "
                "content_sha256, created_by_user_id, row_version, created_at, "
                "updated_at) VALUES "
                "('context-intake', 'context-visit', 1, 'draft', "
                "'Synthetic complaint', 'Synthetic history', '[]', '[]', "
                "'[]', '[]', '[]', '" + "0" * 64 + "', 'context-user', 1, "
                "'2026-09-20 10:00:00', '2026-09-20 10:00:00')"
            ))

        with pytest.raises(RuntimeError, match="clinical context contains data"):
            command.downgrade(config, "f4b14c2d9a01")
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            )) == "a8c15d3e7b02"
            assert connection.scalar(text(
                "SELECT count(*) FROM clinical_intakes"
            )) == 1
    finally:
        engine.dispose()


def test_clinical_safety_migration_refuses_governance_data_loss(
    tmp_path,
    monkeypatch,
):
    url = f"sqlite:///{tmp_path / 'clinical-safety-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        expected_tables = {
            "clinical_safety_rules",
            "clinical_safety_rule_knowledge",
            "clinical_safety_evaluations",
            "clinical_safety_findings",
        }
        assert expected_tables <= set(inspector.get_table_names())
        assert len(inspector.get_foreign_keys("clinical_safety_rules")) == 3
        assert (
            inspector.get_foreign_keys("clinical_safety_rule_knowledge")[0][
                "options"
            ]["ondelete"]
            in {"CASCADE", "RESTRICT"}
        )
        assert len(
            inspector.get_check_constraints("clinical_safety_evaluations")
        ) == 6

        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, role, is_active, "
                "auth_version, failed_login_count, created_at, updated_at) "
                "VALUES ('safety-user', 'safety_user', 'Safety User', "
                "'hash', 'physician', 1, 0, 0, "
                "'2026-09-20 10:00:00', '2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO clinical_safety_rules "
                "(id, rule_key, version, title, description, clinical_domain, "
                "severity, action, message, predicate, status, content_sha256, "
                "created_by_user_id, row_version, created_at, updated_at) "
                "VALUES ('safety-rule', 'MIG-SAFETY-001', 1, "
                "'Synthetic migration rule', "
                "'Synthetic description used only to protect migration data.', "
                "'migration', 'warning', 'review_before_proceeding', "
                "'Synthetic clinician review message.', "
                "'{\"combinator\":\"all\",\"conditions\":[]}', "
                "'draft', '" + "0" * 64 + "', 'safety-user', 1, "
                "'2026-09-20 10:00:00', '2026-09-20 10:00:00')"
            ))

        with pytest.raises(
            RuntimeError,
            match="clinical safety registry contains data",
        ):
            command.downgrade(config, "a8c15d3e7b02")
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            )) == "c92e4b7a1d30"
            assert connection.scalar(text(
                "SELECT count(*) FROM clinical_safety_rules"
            )) == 1
    finally:
        engine.dispose()


def test_clinical_safety_review_migration_refuses_history_loss(
    tmp_path,
    monkeypatch,
):
    url = f"sqlite:///{tmp_path / 'clinical-safety-review-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert "clinical_safety_finding_reviews" in inspector.get_table_names()
        assert len(
            inspector.get_foreign_keys("clinical_safety_finding_reviews")
        ) == 2
        assert len(
            inspector.get_check_constraints("clinical_safety_finding_reviews")
        ) == 9

        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, role, is_active, "
                "auth_version, failed_login_count, created_at, updated_at) "
                "VALUES ('review-user', 'review_user', 'Review User', 'hash', "
                "'physician', 1, 0, 0, '2026-09-20 10:00:00', "
                "'2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO patients "
                "(id, patient_code, first_name, last_name, is_active, "
                "created_at, updated_at) VALUES "
                "('review-patient', 'REV-MIG-001', 'Review', 'Patient', 1, "
                "'2026-09-20 10:00:00', '2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO visits "
                "(id, patient_id, visit_date, status, created_at, updated_at) "
                "VALUES ('review-visit', 'review-patient', "
                "'2026-09-20 10:00:00', 'open', "
                "'2026-09-20 10:00:00', '2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO clinical_safety_rules "
                "(id, rule_key, version, title, description, clinical_domain, "
                "severity, action, message, predicate, status, content_sha256, "
                "created_by_user_id, row_version, created_at, updated_at) "
                "VALUES ('review-rule', 'REV-RULE-001', 1, 'Review rule', "
                "'Synthetic migration rule description for review history.', "
                "'migration', 'warning', 'review_before_proceeding', "
                "'Synthetic review message.', "
                "'{\"combinator\":\"all\",\"conditions\":[]}', "
                "'draft', '" + "1" * 64 + "', 'review-user', 1, "
                "'2026-09-20 10:00:00', '2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO clinical_safety_evaluations "
                "(id, visit_id, report_ids, engine_version, outcome, "
                "evaluated_rule_count, triggered_count, highest_severity, "
                "clinical_context_sha256, rule_set_sha256, result_sha256, "
                "evaluated_by_user_id, created_at) VALUES "
                "('review-evaluation', 'review-visit', '[]', '1.0', "
                "'alerts_present', 1, 1, 'warning', '" + "2" * 64 + "', '" +
                "3" * 64 + "', '" + "4" * 64 + "', 'review-user', "
                "'2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO clinical_safety_findings "
                "(id, evaluation_id, sort_order, rule_id, rule_key, "
                "rule_version, rule_content_sha256, title, severity, action, "
                "message, knowledge_fact_ids, condition_trace, created_at) "
                "VALUES ('review-finding', 'review-evaluation', 1, "
                "'review-rule', 'REV-RULE-001', 1, '" + "1" * 64 + "', "
                "'Review finding', 'warning', 'review_before_proceeding', "
                "'Synthetic review message.', '[]', '[]', "
                "'2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO clinical_safety_finding_reviews "
                "(id, finding_id, sequence, action, disposition, "
                "created_by_user_id, evaluation_result_sha256, "
                "rule_content_sha256, previous_review_sha256, payload, "
                "sha256, created_at) VALUES "
                "('review-event', 'review-finding', 1, 'acknowledged', NULL, "
                "'review-user', '" + "4" * 64 + "', '" + "1" * 64 + "', "
                "NULL, '{}', '" + "5" * 64 + "', "
                "'2026-09-20 10:00:00')"
            ))

        with pytest.raises(
            RuntimeError,
            match="safety finding review history exists",
        ):
            command.downgrade(config, "c92e4b7a1d30")
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            )) == "d51e7a9b2c64"
            assert connection.scalar(text(
                "SELECT count(*) FROM clinical_safety_finding_reviews"
            )) == 1
    finally:
        engine.dispose()


def test_clinical_evidence_brief_migration_refuses_history_loss(
    tmp_path,
    monkeypatch,
):
    url = f"sqlite:///{tmp_path / 'clinical-evidence-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert "clinical_evidence_briefs" in inspector.get_table_names()
        assert len(inspector.get_foreign_keys("clinical_evidence_briefs")) == 3
        assert len(inspector.get_check_constraints("clinical_evidence_briefs")) == 5

        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, role, is_active, "
                "auth_version, failed_login_count, created_at, updated_at) "
                "VALUES ('evidence-user', 'evidence_user', 'Evidence User', "
                "'hash', 'physician', 1, 0, 0, '2026-09-20 10:00:00', "
                "'2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO patients "
                "(id, patient_code, first_name, last_name, is_active, "
                "created_at, updated_at) VALUES "
                "('evidence-patient', 'EVID-MIG-001', 'Evidence', 'Patient', "
                "1, '2026-09-20 10:00:00', '2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO visits "
                "(id, patient_id, visit_date, status, created_at, updated_at) "
                "VALUES ('evidence-visit', 'evidence-patient', "
                "'2026-09-20 10:00:00', 'open', "
                "'2026-09-20 10:00:00', '2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO clinical_intakes "
                "(id, visit_id, version, status, chief_complaint, "
                "history_present_illness, functional_limitations, "
                "relevant_history, current_medications, allergies, "
                "red_flags, content_sha256, created_by_user_id, "
                "finalized_by_user_id, finalized_at, row_version, created_at, "
                "updated_at) VALUES "
                "('evidence-intake', 'evidence-visit', 1, 'final', "
                "'Synthetic complaint', 'Synthetic migration history', "
                "'[]', '[]', '[]', '[]', '[]', '" + "1" * 64 + "', "
                "'evidence-user', 'evidence-user', "
                "'2026-09-20 10:00:00', 1, '2026-09-20 10:00:00', "
                "'2026-09-20 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO clinical_evidence_briefs "
                "(id, visit_id, intake_id, report_ids, "
                "clinical_context_sha256, knowledge_fact_ids, "
                "knowledge_set_sha256, knowledge_as_of, selection_method, "
                "output_type, created_by_user_id, payload, sha256, created_at) "
                "VALUES ('evidence-brief', 'evidence-visit', "
                "'evidence-intake', '[]', '" + "2" * 64 + "', '[]', '" +
                "3" * 64 + "', '2026-09-20', 'clinician_selected', "
                "'evidence_summary', 'evidence-user', '{}', '" + "4" * 64 +
                "', '2026-09-20 10:00:00')"
            ))

        with pytest.raises(
            RuntimeError,
            match="clinical evidence brief history exists",
        ):
            command.downgrade(config, "d51e7a9b2c64")
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            )) == "e6b7c8d9a401"
            assert connection.scalar(text(
                "SELECT count(*) FROM clinical_evidence_briefs"
            )) == 1
    finally:
        engine.dispose()



def test_treatment_outcome_migration_refuses_outcome_history_loss(
    tmp_path,
    monkeypatch,
):
    url = f"sqlite:///{tmp_path / 'treatment-outcome-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert "treatment_outcomes" in inspector.get_table_names()
        assert len(inspector.get_foreign_keys("treatment_outcomes")) == 3
        checks = {
            item["name"]
            for item in inspector.get_check_constraints("treatment_outcomes")
        }
        assert {
            "ck_treatment_outcome_follow_up_day",
            "ck_treatment_outcome_status",
            "ck_treatment_outcome_patient_rating",
            "ck_treatment_outcome_physician_rating",
            "ck_treatment_outcome_pain_score",
            "ck_treatment_outcome_function_score",
            "ck_treatment_outcome_context_sha256",
            "ck_treatment_outcome_treatment_sha256",
            "ck_treatment_outcome_sha256",
        } <= checks

        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, role, is_active, "
                "auth_version, failed_login_count, created_at, updated_at) "
                "VALUES ('outcome-user', 'outcome_user', 'Outcome User', "
                "'hash', 'physician', 1, 0, 0, "
                "'2026-09-22 10:00:00', '2026-09-22 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO patients "
                "(id, patient_code, first_name, last_name, is_active, "
                "created_at, updated_at) VALUES "
                "('outcome-patient', 'OUT-MIG-001', 'Outcome', 'Patient', 1, "
                "'2026-09-22 10:00:00', '2026-09-22 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO visits "
                "(id, patient_id, visit_date, status, created_at, updated_at) "
                "VALUES ('outcome-visit', 'outcome-patient', "
                "'2026-09-22 10:00:00', 'open', "
                "'2026-09-22 10:00:00', '2026-09-22 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO treatments "
                "(id, visit_id, treatment_type, status, session_number, "
                "created_at, updated_at) VALUES "
                "('outcome-treatment', 'outcome-visit', 'ACS', 'completed', 1, "
                "'2026-09-22 10:00:00', '2026-09-22 10:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO treatment_outcomes "
                "(id, treatment_id, visit_id, treatment_type, "
                "clinical_context_sha256, treatment_snapshot_sha256, "
                "finalization_sha256s, follow_up_day, outcome_status, "
                "outcome_measures, adverse_events, created_by_user_id, "
                "payload, sha256, recorded_at) VALUES "
                "('outcome-record', 'outcome-treatment', 'outcome-visit', "
                "'ACS', '" + "1" * 64 + "', '" + "2" * 64 + "', '[]', 42, "
                "'improved', '[]', '[]', 'outcome-user', '{}', '" +
                "3" * 64 + "', '2026-09-22 10:00:00')"
            ))

        with pytest.raises(
            RuntimeError,
            match="treatment outcome history exists",
        ):
            command.downgrade(config, "e6b7c8d9a401")
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            )) == "f7c2d4e8a910"
            assert connection.scalar(text(
                "SELECT count(*) FROM treatment_outcomes"
            )) == 1
    finally:
        engine.dispose()



def test_treatment_decision_migration_refuses_decision_history_loss(
    tmp_path,
    monkeypatch,
):
    url = f"sqlite:///{tmp_path / 'treatment-decision-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert "treatment_decisions" in inspector.get_table_names()
        treatment_columns = {
            item["name"] for item in inspector.get_columns("treatments")
        }
        assert "source_treatment_decision_id" in treatment_columns
        assert "source_treatment_decision_sha256" in treatment_columns
        decision_fks = inspector.get_foreign_keys("treatment_decisions")
        assert len(decision_fks) == 2
        assert {
            tuple(item["constrained_columns"])
            for item in decision_fks
        } == {("visit_id",), ("decided_by_user_id",)}
        treatment_fk_names = {
            item["name"]
            for item in inspector.get_foreign_keys("treatments")
        }
        assert "fk_treatments_source_treatment_decision_id" in treatment_fk_names

        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, role, is_active, "
                "auth_version, failed_login_count, created_at, updated_at) "
                "VALUES ('decision-user', 'decision_user', 'Decision User', "
                "'hash', 'physician', 1, 0, 0, "
                "'2026-09-22 12:00:00', '2026-09-22 12:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO patients "
                "(id, patient_code, first_name, last_name, is_active, "
                "created_at, updated_at) VALUES "
                "('decision-patient', 'DEC-MIG-001', 'Decision', 'Patient', 1, "
                "'2026-09-22 12:00:00', '2026-09-22 12:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO visits "
                "(id, patient_id, visit_date, status, created_at, updated_at) "
                "VALUES ('decision-visit', 'decision-patient', "
                "'2026-09-22 12:00:00', 'open', "
                "'2026-09-22 12:00:00', '2026-09-22 12:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO treatment_decisions "
                "(id, visit_id, decision_type, clinical_context_sha256, "
                "roadmap_sha256, selected_protocols, rationale, "
                "evidence_brief_ids, decided_by_user_id, payload, sha256, "
                "decided_at) VALUES "
                "('decision-record', 'decision-visit', 'defer', '" +
                "1" * 64 + "', '" + "2" * 64 + "', '[]', "
                "'Synthetic migration decision rationale.', '[]', "
                "'decision-user', '{}', '" + "3" * 64 + "', "
                "'2026-09-22 12:00:00')"
            ))

        with pytest.raises(
            RuntimeError,
            match="clinician treatment decision history exists",
        ):
            command.downgrade(config, "f7c2d4e8a910")
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            )) == "a3e5c7d9b120"
            assert connection.scalar(text(
                "SELECT count(*) FROM treatment_decisions"
            )) == 1
    finally:
        engine.dispose()



def test_protocol_governance_migration_refuses_history_loss(
    tmp_path,
    monkeypatch,
):
    url = f"sqlite:///{tmp_path / 'protocol-governance-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        assert "protocol_governance_cases" in inspector.get_table_names()
        assert "protocol_governance_reviews" in inspector.get_table_names()
        assert len(inspector.get_foreign_keys("protocol_governance_cases")) == 1
        assert len(inspector.get_foreign_keys("protocol_governance_reviews")) == 2

        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users "
                "(id, username, display_name, password_hash, role, is_active, "
                "auth_version, failed_login_count, created_at, updated_at) "
                "VALUES ('gov-user', 'gov_user', 'Governance User', 'hash', "
                "'physician', 1, 0, 0, '2026-09-22 18:00:00', "
                "'2026-09-22 18:00:00')"
            ))
            connection.execute(text(
                "INSERT INTO protocol_governance_cases "
                "(id, protocol_code, protocol_version, treatment_type, "
                "case_type, source_learning_review_sha256, protocol_snapshot, "
                "learning_snapshot, rationale, evidence_needed, "
                "created_by_user_id, payload, sha256, created_at) VALUES "
                "('gov-case', 'GOV', '1.0', 'ACS', 'collect_more_data', '" +
                "1" * 64 + "', '{}', '{}', 'Synthetic governance rationale', "
                "'[]', 'gov-user', '{}', '" + "2" * 64 + "', "
                "'2026-09-22 18:00:00')"
            ))

        with pytest.raises(
            RuntimeError,
            match="protocol governance history exists",
        ):
            command.downgrade(config, "a3e5c7d9b120")
        with engine.connect() as connection:
            assert connection.scalar(text(
                "SELECT version_num FROM alembic_version"
            )) == "b7d4e6f8c230"
            assert connection.scalar(text(
                "SELECT count(*) FROM protocol_governance_cases"
            )) == 1
    finally:
        engine.dispose()
