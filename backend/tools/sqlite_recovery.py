"""Explicit-path SQLite inspection, consistent backup and new-copy rehearsal.

No command replaces an existing file or modifies the source database's data.
Backups are not encrypted; store them with approved filesystem protection.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time


class RecoveryError(Exception):
    pass


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def open_source(source, deadline):
    source = Path(source).resolve(strict=True)
    if not source.is_file():
        raise RecoveryError("Source must be an existing SQLite file.")
    connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=1)
    connection.execute("PRAGMA query_only=ON")
    connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return connection


def inspect_connection(connection):
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise RecoveryError("SQLite integrity check failed; no data details are printed.")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RecoveryError("SQLite foreign-key check failed; no patient data is printed.")
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    revisions = []
    if "alembic_version" in tables:
        revisions = [row[0] for row in connection.execute("SELECT version_num FROM alembic_version LIMIT 5")]
        if len(revisions) != 1 or not re.fullmatch(r"[a-zA-Z0-9_]{1,32}", revisions[0]):
            raise RecoveryError("Unexpected migration revision metadata.")
    return {"status": "verified", "table_count": len(tables), "revisions": revisions}


def inspect_database(source, timeout=30):
    with closing(open_source(source, time.monotonic() + timeout)) as connection:
        return inspect_connection(connection)


def verified_copy(source, destination, *, expected_sha256=None, timeout=30):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise RecoveryError("Destination already exists; overwriting is never allowed.")
    if expected_sha256 is not None:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
            raise RecoveryError("A valid backup SHA-256 is required.")
        if file_digest(source) != expected_sha256.lower():
            raise RecoveryError("Backup checksum mismatch; restore refused.")
        wal = source.with_name(source.name + "-wal")
        if wal.exists() and wal.stat().st_size:
            raise RecoveryError("Restore requires a quiescent single-file backup, not an active WAL database.")
    deadline = time.monotonic() + timeout
    # Reserve exclusively, with restrictive Unix permissions. Windows inherits
    # the destination directory ACL; do not claim that chmod encrypts a backup.
    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise RecoveryError("Backup timed out.")
        with closing(open_source(source, deadline)) as reader:
            with closing(sqlite3.connect(destination)) as writer:
                reader.backup(writer, pages=128, progress=progress, sleep=0.1)
                writer.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                result = inspect_connection(writer)
        # A restore source must be a quiescent backup, not an actively changing DB.
        if expected_sha256 is not None and file_digest(source) != expected_sha256.lower():
            raise RecoveryError("Backup changed during restore; restore refused.")
        if expected_sha256 is not None:
            wal = source.with_name(source.name + "-wal")
            if wal.exists() and wal.stat().st_size:
                raise RecoveryError("Backup acquired WAL data during restore; restore refused.")
        result["sha256"] = file_digest(destination)
        return result
    except Exception:
        # Only the file reserved by this invocation can be removed here.
        destination.unlink()
        raise


def rehearse_upgrade(source, destination, *, expected_sha256, timeout=60):
    """Upgrade only a NEW verified copy, never a configured/live database."""
    verified_copy(source, destination, expected_sha256=expected_sha256, timeout=timeout)
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment.update({
        "DATABASE_URL": "sqlite:///" + Path(destination).resolve().as_posix(),
        "ENVIRONMENT": "test", "DEBUG": "false", "BOOTSTRAP_ENABLED": "false",
    })
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"],
        cwd=root, env=environment, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode:
        raise RecoveryError("Migration rehearsal failed; the new copy is retained for local inspection.")
    report = inspect_database(destination, timeout)
    report["sha256"] = file_digest(destination)
    report["status"] = "rehearsal_passed"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inspect", "backup", "restore-copy", "rehearse-upgrade"])
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination")
    parser.add_argument("--sha256")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 600:
        parser.error("timeout must be between 1 and 600 seconds")
    if args.action != "inspect" and not args.destination:
        parser.error("destination is required")
    if args.action in {"restore-copy", "rehearse-upgrade"} and not args.sha256:
        parser.error("a previously recorded backup sha256 is required")
    try:
        if args.action == "inspect":
            result = inspect_database(args.source, args.timeout)
        elif args.action == "rehearse-upgrade":
            result = rehearse_upgrade(args.source, args.destination, expected_sha256=args.sha256, timeout=args.timeout)
        else:
            result = verified_copy(args.source, args.destination, expected_sha256=args.sha256, timeout=args.timeout)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (RecoveryError, OSError, sqlite3.Error, subprocess.SubprocessError):
        # Do not log database content, connection strings, or inherited secrets.
        print(json.dumps({"status": "failed", "message": "Operation refused or failed. Check paths, checksum, available space and database health. Existing destinations are never overwritten."}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
