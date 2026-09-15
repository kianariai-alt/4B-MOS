# 4B-MOS backend

FastAPI/SQLAlchemy clinic workflow backend. This repository is not yet a complete
deployed clinic product. Do not expose development defaults to the internet.

Completed-session evidence remains immutable. Any later correction or supplement
is stored as a separate append-only amendment with an immutable review decision;
the original finalization record is never rewritten.

Install dependencies in an isolated environment and verify from the repository root:

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest backend/tests -q
```

Pull requests additionally migrate a disposable PostgreSQL 18 database and run
the PostgreSQL-specific isolation, row/table-lock, timeout, deadlock and amendment
sequence tests on Python 3.12 and 3.14. No external or production database is used.

See [release readiness](docs/RELEASE_READINESS.md) for clinical limitations and
[the operations runbook](docs/OPERATIONS_RUNBOOK.md) for staged installation,
production settings, explicit-path SQLite backups and new-copy upgrade rehearsals.
No production migration or server deployment is performed by the test command.
