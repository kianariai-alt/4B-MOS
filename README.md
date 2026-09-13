# 4B-MOS backend

FastAPI/SQLAlchemy clinic workflow backend. This repository is not yet a complete
deployed clinic product. Do not expose development defaults to the internet.

Install dependencies in an isolated environment and verify from the repository root:

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest backend/tests -q
```

See [release readiness](docs/RELEASE_READINESS.md) for clinical limitations and
[the operations runbook](docs/OPERATIONS_RUNBOOK.md) for staged installation,
production settings, explicit-path SQLite backups and new-copy upgrade rehearsals.
No production migration or server deployment is performed by the test command.
