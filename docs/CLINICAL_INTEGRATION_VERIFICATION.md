# Clinical Integration — verification record

Scope: experimental integration foundation, synthetic data only. No clinic
database, live imaging center, remote model, operational deployment or main
merge was used.

## Local environment and baseline

- Python 3.12.14; isolated virtual environment with the repository's pinned
  `backend/requirements.txt` and `backend/requirements-dev.txt`.
- Base: main `bc6fb3f15825d6eaccaa45503ad61a432baf1c5b`.
- Existing context/Registry/safety/Copilot baseline: **74 passed**.
- New integration tests use existing in-memory SQLite fixtures and disposable
  migration files. Explicit test settings point to scratch databases.

## Final checks

- Final complete backend suite: **775 passed, 19 skipped, 6 warnings**, in
  203.55 seconds. The skipped cases require a disposable PostgreSQL service,
  which is not installed locally. Warnings concern the existing Starlette/httpx
  adapter and SQLite datetime adapter deprecations.
- All **40 new local integration/contract/migration cases passed** as part of
  that complete run. One additional concurrent retry test is in the PostgreSQL
  CI harness; its local skip is not a pass.
- `python -m compileall -q backend`: passed.
- `git diff --check`: passed.
- Fresh disposable database: `alembic upgrade head`, `alembic check`,
  `alembic current` and `alembic heads`: passed; one head `b12f6c8d4a90`, no
  new upgrade operations detected.
- New migration test verifies preservation of existing rows, metadata agreement,
  safe empty downgrade/re-upgrade and refusal to discard integration evidence.
- OpenAPI generation: six new integration/companion route paths generated.
- Standalone synthetic demo: two cores, exactly one clinical and one imaging
  finding, source/review provenance and no diagnostic or treatment authority.
- [Versioned synthetic result](examples/clinical-integration-synthetic-result.json)
  parses successfully as `DecisionSupportResult`.
- Published producer JSON Schema matches the Pydantic contract in a dedicated
  compatibility test.

## CI and remaining validation

The existing Backend CI workflow runs Python 3.12 and 3.14 backend suites,
fresh SQLite migrations, PostgreSQL 18 migrations/integration tests and a
production-container smoke test. The new concurrent integration retry test is
included in its existing PostgreSQL test module. Use the PR's checks for the
authoritative result at the reviewed commit; local skipped cases are not claimed
as passed.

These are software verification results, not clinical validation or authorization
for patient use. Live specialist inference, DICOM identity/quality, model-specific
physician review and real UI integration remain deferred as described in the
[architecture and workstream handoff](CLINICAL_INTELLIGENCE_INTEGRATION.md).
