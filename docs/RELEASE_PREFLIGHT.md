# Release preflight

The release preflight is a read-only, fail-closed check for the configured
4B-MOS backend environment. Run it after the database upgrade and isolated
administrator setup, while old workers remain drained and before accepting
traffic.

It does not deploy code, migrate the database, create accounts, read clinical
records or authorize a production release.

## Run

Load the reviewed private production environment through the deployment
system, then run from the repository root with the release interpreter:

```sh
python -m backend.tools.release_preflight
```

For automation, request structured output:

```sh
python -m backend.tools.release_preflight --format json
```

Exit status `0` means every required check passed. Exit status `1` means at
least one check failed or was blocked. Invalid application configuration also
terminates non-zero during settings validation.

The command never prints the database URL, exception text, usernames,
administrator counts, password hashes, signing key or patient data. Its output
contains only application metadata, the database dialect, the expected schema
revision and the fixed codes below.

## Required checks

| Check | Passing code | Failure behavior |
| --- | --- | --- |
| Runtime configuration | `production_runtime_safe` | Requires production mode with debug and public bootstrap disabled. Unsafe production settings are also rejected by application startup validation. |
| Database schema | `database_schema_ready` | Fails for an unreachable/uninitialized database, a revision other than the application head, missing critical tables or disabled SQLite foreign keys. |
| Active administrator | `active_administrator_present` | Fails when no active administrator exists. It is blocked when the schema check fails. |

SQLite also emits `sqlite_serializes_database_writers`. This warning does not
change the exit status, but it requires explicit review because SQLite cannot
provide PostgreSQL's independent row-lock concurrency.

## Deployment order

1. Keep old workers drained and preserve the verified backup and restore plan.
2. Upgrade the selected database to the release's single Alembic head.
3. Complete initial administrator creation only through the reviewed isolated
   setup; disable public bootstrap before production startup.
4. Load the private production configuration and run this preflight.
5. Record the application commit, expected revision and preflight result in the
   release record.
6. Start only the new workers, then verify `/api/v1/health` and
   `/api/v1/health/ready` before enabling traffic.

Do not weaken a failed check to force a release. Correct the environment or
database state and run the command again.

## Explicit limitations

This tool does not validate HTTPS, reverse-proxy or firewall policy, encrypted
backup storage, restore ownership, monitoring/alert delivery, database load or
failover, external identity, notification and retention rules, legal signatures,
clinical policy or user-interface acceptance. Those remain independent release
decisions and evidence.
