# Controlled local installation and recovery

This is a backend release candidate, not authorization for production deployment.
No live clinic database, remote branch, hosted service or external credential was
changed by the development work. Windows and PostgreSQL remain unverified.

## Installation order

Use the numbered bundle manifest, not a mixture of earlier cumulative archives.
Stage 1 integrates clinical atomicity, concurrency and completion evidence from
the exact `56df1fa` base. Stage 2 hardens runtime configuration/auth/readiness.
Stage 3 adds recovery and installation tools. Review and commit each stage before
applying the next. The installer checks committed Git **tree** hashes, so your
local commit messages/IDs may differ without losing the content check.

The separate stage-4 add-on protects the last active administrator. Apply it
only after all three original stages have been committed. Its manifest checks
the exact stage-3 output tree and uses the same installer with `--stage 4`.

The installer requires a clean `review/` branch and refuses unrelated changes,
wrong-order patches and checksum mismatches. It does not commit, push, reset,
run tests, install packages, create a database, or execute migrations. Patch
hashes detect accidental package corruption, not a malicious replacement of
both the bundle and its manifest. Keep a trusted copy of the delivered archive.

## Development environment

Create a virtual environment outside the repository if none exists. Use that
interpreter consistently to install both requirements files and run:

```sh
python -m pytest backend/tests -q
```

Run local development on `127.0.0.1`. A test pass is not clinical validation.
First administrator creation must occur in a reviewed isolated setup before
turning on production settings. Do not expose the development bootstrap to a
public network. Production startup requires `ENVIRONMENT=production`,
`DEBUG=false`, `BOOTSTRAP_ENABLED=false` and a privately generated strong key.
The sample environment file intentionally contains a rejected placeholder.
Existing project-generated JWTs contain the now-required `sub`, `iat`, `exp`
claims. Rotating the signing key invalidates existing tokens.

Do not send secrets or patient data in screenshots, logs or chat. Production
must still have HTTPS, restricted database/file access, login rate limiting,
monitoring, recovery ownership and a reviewed retention policy. These are not
configured by this package. Disabling API docs is not an authorization control.
Password changes do not currently revoke already-issued JWTs; token revocation
remains future security work. Stage 4 refuses disabling/demoting the last active
administrator with HTTP 409. An inactive admin does not count as a successor.
Create/activate a second administrator before handing off the current account.
This does not repair a database that already has no active administrators.

Account creation, updates and bootstrap use the same transaction lock. Mutation
routes recheck the actor's active-admin status after acquiring it, so a request
authorized before a concurrent revocation cannot silently retain that authority.
Explicit null and unknown user-PATCH fields now return 422. No new migration is
needed; the schema remains `a71d92cfe604`. PostgreSQL account mutations require
READ COMMITTED isolation and have not been tested on a live PostgreSQL server.
Drain older unlocked workers before enabling the new account-write paths.
Direct SQL and internal repository-only writes can bypass the service guard;
database privileges remain separate work; dedicated account-audit events are
provided by the stage-5 add-on below.

Stage 5 adds dedicated `admin_bootstrapped`, `user_created` and `user_updated`
events, committed in the same transaction as the account changes. An allowlist
captures only username, display name, role and active status. Password resets
record an action flag, never the password/hash. Actor attribution is captured
before self-renames/demotions. No-op edits emit no event. Trusted internal calls
without an actor and unauthenticated bootstrap are labeled explicitly.

Only active admins may read `GET /api/v1/users/{id}/audit-logs`, with `skip` and
`limit` pagination (maximum 500). Clinical-audit reader roles do not grant this
access. Old changes are not reconstructed. Failed attempts and login activity
are not recorded by these success events; security monitoring remains separate.
There is no audit-edit API, but privileged SQL can still modify these records;
they are not a cryptographic or legally certified audit store. Stage 5 requires
stage 4's committed output and introduces no new schema migration.

## Readiness and migration gate

`GET /api/v1/health` reports process liveness only.
`GET /api/v1/health/ready` reports 200 only with the expected revision, critical
tables and (for SQLite) FK enforcement. It returns a redacted 503 otherwise.
The head is `a71d92cfe604`; upgrade a disposable copy and inspect the result
before any production change. Installing code does NOT upgrade the database.

Drain old workers before upgrades; never mix locked and old unlocked clinical
writers. For a future production change, record the source revision, application
commit, maintenance window, verified backup hash and recovery destination.
Rehearse restoration and clinician acceptance on test data before approval.

## SQLite tools: explicit paths, no overwrite

These tools use Python's standard-library SQLite backup API, which includes
committed WAL data. Do not substitute an ordinary file copy of a live SQLite DB.
No command restores over an existing file; select a NEW destination every time.
The source is opened read-only (SQLite may use shared-memory sidecars, but the
tool does not modify source database data). Output contains no patient rows or
connection secrets. Integrity/FK checks are structural, not clinical validation.

Run from the repository root with the same environment as the app. Replace all
example paths with reviewed explicit paths; never paste guesses about the live DB.

```sh
python -m backend.tools.sqlite_recovery inspect --source "/explicit/source.db"
python -m backend.tools.sqlite_recovery backup --source "/explicit/source.db" --destination "/protected/new-backup.db"
```

Record the returned SHA-256 with the backup in protected storage. For recovery
testing, use a quiescent backup and its recorded checksum:

```sh
python -m backend.tools.sqlite_recovery restore-copy --source "/protected/new-backup.db" --destination "/test/new-restored.db" --sha256 RECORDED_HASH
python -m backend.tools.sqlite_recovery rehearse-upgrade --source "/protected/new-backup.db" --destination "/test/new-upgraded.db" --sha256 RECORDED_HASH
```

`rehearse-upgrade` sets DATABASE_URL only for its Alembic subprocess to the newly
created copy. It never edits `.env` or points the running clinic app at that copy.
A migration failure leaves that NEW copy for local investigation. An incomplete
backup is removed only if the tool itself exclusively created that destination.
There is no automatic production rollback. Switching a clinic back to a backup
can lose newer records and requires a separate approved reconciliation plan.

Backups contain sensitive data and password hashes. They are **not encrypted**
by this utility. Use approved encrypted storage and restricted Windows ACLs or
Unix permissions; do not upload backups here. Windows permission behavior has
not been certified. No script deletes old backups automatically.

## Rollback limitations

Evidence-preserving downgrade refuses populated finalization tables and offline
downgrade. Never bypass this by deleting reports. Older administration-table
downgrades are destructive. Recoverable source control changes do not imply
recoverable database changes. Preserve failed rehearsal copies separately; do
not try repeated upgrades on the only backup.

## Deferred decisions, not silently enabled features

- Amendments: who may author, approve, reject and view them; reason vocabulary;
  correction versus supplement; whether original sign-off is legally required.
- Clinical policy: expiry-date boundary/timezone; absent-administration outcomes;
  deviation acknowledgment and override authority. Existing rules are unchanged.
- Product: mobile clinical UI, deployment host, access boundaries and data retention.

These do not block delivery of the tested technical package, but do block calling
the whole product production-ready. No clinical sign-off or amendment API is
enabled merely by installing this release.
