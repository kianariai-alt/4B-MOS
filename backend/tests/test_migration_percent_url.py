import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from backend.app.core.database_revision import EXPECTED_DATABASE_REVISION


def test_real_migration_accepts_a_database_url_containing_percent(tmp_path):
    database = tmp_path / "synthetic%database.sqlite"
    environment = {**os.environ, "ENVIRONMENT": "test", "DEBUG": "false",
                   "DATABASE_URL": "sqlite:///" + database.as_posix()}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).resolve().parents[2], env=environment,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == EXPECTED_DATABASE_REVISION
