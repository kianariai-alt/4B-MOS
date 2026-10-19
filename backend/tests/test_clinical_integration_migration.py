"""Migration checks on disposable databases, never the configured clinic store."""

from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text

from backend.app.core.config import settings
from backend.app.core.database_revision import EXPECTED_DATABASE_REVISION


def test_integration_migration_preserves_old_rows_checks_metadata_and_guards_downgrade(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'synthetic-integration-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "a1d4e7f0b386")
    engine = create_engine(url)
    now = datetime.now(timezone.utc).isoformat()
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO patients (id, patient_code, first_name, last_name, is_active, created_at, updated_at) VALUES ('synthetic-patient', 'SYNTHETIC', 'Test', 'Fixture', 1, :stamp, :stamp)"), {"stamp": now})
        command.upgrade(config, "head")
        command.check(config)
        engine.dispose()  # Do not reuse SQLite connections opened before DDL.
        inspector = inspect(engine)
        assert len(inspector.get_foreign_keys("clinical_integration_runs")) == 2
        assert len(inspector.get_foreign_keys("clinical_integration_reviews")) == 2
        assert all(fk["options"]["ondelete"] == "RESTRICT" for name in (
            "clinical_integration_runs", "clinical_integration_reviews",
        ) for fk in inspector.get_foreign_keys(name))
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT patient_code FROM patients WHERE id='synthetic-patient'")) == "SYNTHETIC"
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_DATABASE_REVISION
        command.downgrade(config, "a1d4e7f0b386")
        engine.dispose()
        assert "clinical_integration_runs" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        engine.dispose()
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO users (id, username, display_name, password_hash, role, is_active, failed_login_count, auth_version, created_at, updated_at) VALUES ('synthetic-actor', 'migration_actor', 'Fixture', 'unused', 'physician', 1, 0, 0, :stamp, :stamp)"), {"stamp": now})
            connection.execute(text("INSERT INTO visits (id, patient_id, status, visit_date, created_at, updated_at) VALUES ('synthetic-visit', 'synthetic-patient', 'open', :stamp, :stamp, :stamp)"), {"stamp": now})
            connection.execute(text("INSERT INTO clinical_integration_runs (id, visit_id, request_key, request_sha256, created_by_user_id, created_at, result_sha256, payload) VALUES ('synthetic-run', 'synthetic-visit', 'key', :hash, 'synthetic-actor', :stamp, :hash, '{}')"), {"stamp": now, "hash": "a" * 64})
        with pytest.raises(RuntimeError, match="integration evidence would be lost"):
            command.downgrade(config, "a1d4e7f0b386")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM clinical_integration_runs")) == 1
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == EXPECTED_DATABASE_REVISION
    finally:
        engine.dispose()
