# Controlled local installation and recovery

This is a backend release candidate, not authorization for production deployment.
No live clinic database, hosted service or external credential was changed by the
development work. Stage 7 was validated on Windows; Stage 8 adds disposable
PostgreSQL 18 CI validation and Stage 9 adds persistent known-account login
throttling. No production PostgreSQL service has been certified.

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
New project-generated JWTs contain the required `sub`, `iat`, `exp`, `ver`
claims. Stage 6 intentionally rejects earlier tokens, requiring every user to
log in again. Signing-key rotation remains the global emergency invalidation.

Do not send secrets or patient data in screenshots, logs or chat. Production
must still have HTTPS, restricted database/file access, edge/source login
throttling, alerting, monitoring, recovery ownership and a reviewed retention
policy. Account-bound throttling alone does not configure these controls.
Disabling API docs is not an authorization control.
Stage 6 revokes already-issued account JWTs after password, role or active-status
changes. It does not provide refresh tokens, logout or device/session inventory;
Stage 9 separately provides account-bound login throttling. Stage 4 refuses
disabling/demoting the last active
administrator with HTTP 409. An inactive admin does not count as a successor.
Create/activate a second administrator before handing off the current account.
This does not repair a database that already has no active administrators.

Account creation, updates and bootstrap use the same transaction lock. Mutation
routes recheck the actor's active-admin status after acquiring it, so a request
authorized before a concurrent revocation cannot silently retain that authority.
Explicit null and unknown user-PATCH fields now return 422. Stage 4 itself needs
no migration. PostgreSQL account mutations require
READ COMMITTED isolation. The locking behavior is exercised against an ephemeral
PostgreSQL 18 service in CI, but the intended managed/production database still
requires its own load, failover and connection-pool rehearsal.
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
are not recorded by these success events; Stage 9 adds separate future login
failure/recovery events while alert delivery and security monitoring remain
deployment responsibilities.
There is no audit-edit API, but privileged SQL can still modify these records;
they are not a cryptographic or legally certified audit store. Stage 5 requires
stage 4's committed output and introduces no new schema migration.

Stage 6 requires stage 5 and migration `b36e7f0a1d42`. Drain every old worker,
upgrade the database, deploy only the new code, and require fresh login; never
run a mixed-version deployment. Password, role and active-status changes
increment `auth_version` atomically and record `sessions_revoked: true` in the
audit event. Display-name/no-op changes keep tokens. A downgrade is refused once
any version is non-zero because it could restore a revoked session. Do not zero
the column to bypass the guard; rotate the signing key and use reviewed recovery.

Stage 7 requires stage 6 and migration `d9a4c7e2f1b6`. It adds append-only
session amendments and separate append-only review decisions. It never changes
the captured finalization payload. Admin, physician and nurse roles may author;
admin and physician roles may review; only an admin may decide an amendment they
authored. All existing finalization-read roles may view amendments. Rejections
require a comment. Every amendment requires one of `data_entry_error`,
`omitted_information`, `clinical_clarification`, `late_result` or `other`, plus
a detailed explanation. Types are `correction` and `supplement`.

The API provides `POST` and `GET` on
`/api/v1/treatment-sessions/{session_id}/amendments`, detail `GET` on
`/api/v1/treatment-sessions/{session_id}/amendments/{amendment_id}`, and one
final `POST` to the detail path's `/review` suffix. There are no PATCH or DELETE
endpoints. A rejected amendment remains part of the record and any subsequent
correction is a new amendment. Creation/review audit events contain identifiers,
reason/type and checksums, not duplicated clinical statement text. Sessions
without captured finalization evidence return 404 and are not reconstructed.
SHA-256 is corruption detection, not a digital signature.

Stage 8 requires the Stage 7 head but introduces no schema migration. It adds
the pinned PostgreSQL driver, bounded runtime lock waits and an isolated CI job.
`TEST_POSTGRESQL_URL` is test-only and must always identify a disposable database;
the test guard requires its database name to end in `_ci` or `_test`. The CI
workflow supplies its own service and does not read a repository secret.

Stage 9 requires Stage 8 and migration `e21f6a9c3b40`. It stores a failure
counter, observation-window start and temporary-lock expiry on each user. The
defaults are five failures in 900 seconds and a 300-second lock:

```text
LOGIN_MAX_FAILURES=5
LOGIN_FAILURE_WINDOW_SECONDS=900
LOGIN_LOCKOUT_SECONDS=300
```

Review all three together; accepted ranges are 2-20 failures, 60-86400 seconds
for the window and 30-86400 seconds for the lock. Wrong-password, inactive,
locked and missing-user responses intentionally share one 401 response. Unknown
usernames still pay password-verification cost but are not retained, so use an
approved reverse proxy/gateway for source-based spray protection. Active locks
do not create repeated audit rows or extend themselves. A correct login after
expiry clears state; an administrator password reset clears it immediately and
records that recovery in the existing account audit event.

Known failures create allowlisted `login_failed` events, and successful recovery
after failures creates `login_throttle_cleared`. They contain counts and flags,
not submitted credentials, hashes, raw usernames or client IPs. This is useful
account history, not a SIEM, alerting service or approved retention solution.
PostgreSQL serializes the same account with a row lock while unrelated account
logins remain independent. SQLite still serializes all writers. A bounded lock
conflict returns 503 plus `Retry-After: 1`; clients may retry once after waiting
but must not loop aggressively.

## Readiness and migration gate

The repository's `Backend CI` workflow is the merge gate for pull requests into
`main`. It verifies Python 3.12 and 3.14 against a new disposable SQLite database
and the full backend suite, plus a new disposable PostgreSQL 18 database and the
PostgreSQL migration/concurrency suite. Configure branch protection to require
the stable `Backend CI` status after its first successful run. A green CI result
is an engineering gate only; it does not authorize a production migration or
replace deployment-specific database, restore, security and clinical acceptance
gates below.

For PostgreSQL, use a `postgresql+psycopg://...` URL and set
`DATABASE_LOCK_TIMEOUT_MS` to a reviewed value from 100 through 30000. The
default is 5000 ms. This timeout bounds waits for participating service locks;
it is not a general query timeout and does not make direct SQL concurrency-safe.

`GET /api/v1/health` reports process liveness only.
`GET /api/v1/health/ready` reports 200 only with the expected revision, critical
tables and (for SQLite) FK enforcement. It returns a redacted 503 otherwise.
The head is `e21f6a9c3b40`; upgrade a disposable copy and inspect the result
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

Evidence-preserving downgrade refuses populated amendment or finalization tables
and refuses offline downgrade. Never bypass this by deleting reports, amendments
or review decisions. Older administration-table
downgrades are destructive. Recoverable source control changes do not imply
recoverable database changes. Preserve failed rehearsal copies separately; do
not try repeated upgrades on the only backup.

The Stage 9 downgrade refuses active login counters/windows/locks and refuses
offline downgrade. Do not erase that state to force old authentication code back
into service. A rollback requires a reviewed maintenance window and recovery
plan; old workers do not enforce the new account locks.

## Deferred decisions, not silently enabled features

- Amendments: whether an independent legal/clinical signature, external timestamp,
  notifications, escalation or a stricter retention policy is required.
- Clinical policy: expiry-date boundary/timezone; absent-administration outcomes;
  deviation acknowledgment and override authority. Existing rules are unchanged.
- Product: mobile clinical UI, deployment host, access boundaries and data retention.

These do not block delivery of the tested technical package, but do block calling
the whole product production-ready. Installing the migration does not constitute
clinical or legal approval of the amendment policy.
