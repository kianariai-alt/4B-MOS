from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text

from backend.app.core.config import settings


def test_portal_migration_preserves_data_and_refuses_evidence_loss(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'portal-migration.db'}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "head")
    command.check(config)
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO portal_sessions (id, token_hash, csrf_token, expires_at, created_at) VALUES ('session', :token, :csrf, :stamp, :stamp)"), {"token": "a" * 64, "csrf": "b" * 64, "stamp": datetime.now(timezone.utc)})
            connection.execute(text("INSERT INTO portal_requests (id, session_id, request_key, receipt, content_hash, encrypted_content, state, created_at) VALUES ('request', 'session', 'request-key', 'MOS-SYNTHETIC', :hash, :cipher, 'submitted', :stamp)"), {"hash": "c" * 64, "cipher": b"synthetic-ciphertext", "stamp": datetime.now(timezone.utc)})
        with pytest.raises(RuntimeError, match="patient submissions would be lost"):
            command.downgrade(config, "f0c3d6b1a275")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT COUNT(*) FROM portal_requests")) == 1
    finally:
        engine.dispose()
