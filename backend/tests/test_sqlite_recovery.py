from contextlib import closing
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
import pytest

from backend.app.core.config import settings
from backend.app.core.database_revision import EXPECTED_DATABASE_REVISION
from backend.tools.sqlite_recovery import (
    RecoveryError, file_digest, inspect_database, main, rehearse_upgrade, verified_copy,
)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO sample VALUES (1, 'original')")
        db.commit()
    return path


def test_backup_and_restore_are_new_verified_copies(source, tmp_path):
    original = source.read_bytes()
    backup = tmp_path / "backup.db"
    result = verified_copy(source, backup)
    assert result["sha256"] == file_digest(backup)
    assert source.read_bytes() == original
    restored = tmp_path / "restored.db"
    verified_copy(backup, restored, expected_sha256=result["sha256"])
    with closing(sqlite3.connect(restored)) as db:
        assert db.execute("SELECT value FROM sample").fetchone() == ("original",)


def test_backup_includes_committed_wal_data(source, tmp_path):
    with closing(sqlite3.connect(source)) as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        db.execute("INSERT INTO sample VALUES (2, 'wal-only')")
        db.commit()
        assert source.with_name(source.name + "-wal").stat().st_size > 0
        backup = tmp_path / "wal-backup.db"
        verified_copy(source, backup)
        with closing(sqlite3.connect(backup)) as check:
            assert check.execute("SELECT count(*) FROM sample").fetchone()[0] == 2
        with pytest.raises(RecoveryError, match="quiescent"):
            verified_copy(source, tmp_path / "unsafe-restore.db", expected_sha256=file_digest(source))


@pytest.mark.parametrize("kind", ["existing", "same", "wrong_hash", "missing"])
def test_refuses_unsafe_targets_without_overwriting(source, tmp_path, kind):
    original = source.read_bytes()
    target = tmp_path / "target.db"
    kwargs = {}
    if kind == "existing":
        target.write_bytes(b"keep this file")
    if kind == "same":
        target = source
    if kind == "wrong_hash":
        kwargs["expected_sha256"] = "0" * 64
    origin = tmp_path / "missing.db" if kind == "missing" else source
    with pytest.raises((RecoveryError, FileNotFoundError)):
        verified_copy(origin, target, **kwargs)
    assert source.read_bytes() == original
    if kind == "existing":
        assert target.read_bytes() == b"keep this file"
    if kind in {"wrong_hash", "missing"}:
        assert not target.exists()
    assert not (tmp_path / "missing.db").exists()


def test_foreign_key_violation_rejects_backup(source, tmp_path):
    with closing(sqlite3.connect(source)) as db:
        db.execute("CREATE TABLE invalid_child (parent INTEGER REFERENCES sample(id))")
        db.execute("INSERT INTO invalid_child VALUES (999)")
        db.commit()
    target = tmp_path / "rejected.db"
    with pytest.raises(RecoveryError, match="foreign-key"):
        verified_copy(source, target)
    assert not target.exists()


def test_invalid_database_does_not_leave_partial_backup(tmp_path):
    source = tmp_path / "not-a-db"
    source.write_bytes(b"not a database containing sensitive details")
    target = tmp_path / "rejected.db"
    with pytest.raises(sqlite3.Error):
        verified_copy(source, target)
    assert not target.exists()


def test_cli_failure_redacts_paths_and_content(tmp_path, capsys):
    result = main(["inspect", "--source", str(tmp_path / "private-patient-name.db")])
    output = capsys.readouterr().out
    assert result == 1
    assert "private-patient-name" not in output


def test_rehearsal_upgrades_only_a_new_copy(tmp_path, monkeypatch):
    source = tmp_path / "old schema.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{source}")
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(config, "c68b24017654")
    before = file_digest(source)
    restored = tmp_path / "rehearsal copy.db"
    result = rehearse_upgrade(source, restored, expected_sha256=before)
    assert result["status"] == "rehearsal_passed"
    assert result["revisions"] == [EXPECTED_DATABASE_REVISION]
    assert file_digest(source) == before
    assert inspect_database(source)["revisions"] == ["c68b24017654"]
    with pytest.raises(RecoveryError, match="exists"):
        rehearse_upgrade(source, restored, expected_sha256=before)
