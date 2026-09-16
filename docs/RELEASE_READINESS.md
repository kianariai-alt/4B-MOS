# Release readiness

This repository is a backend API, not yet a complete deployed clinic product.
No production patient database was accessed during this work.

## This change

- Treatment-plan component CRUD, administration component CRUD and operational
  workflow transitions now commit together with their audit records.
- Repository writes in these paths flush; top-level service commands own the
  commit and roll back on failure. Other legacy services retain their existing
  transaction behavior and require a separate audit.
- Failure-injection tests cover create/update/delete, audit failure before and
  after flush, commit failure, and failure of the second workflow audit event.
- An Alembic regression test upgrades a populated disposable SQLite database
  from the previous head and verifies a downgrade/upgrade round trip.
- The finalization-evidence stage adds migration `a71d92cfe604`; no clinical
  completion policy is changed.
- Session creation and documentation edits now also commit with audit records.
  Documentation audit events include the actor, changed fields and JSON-safe
  before/after values; no-op edits do not emit misleading update events.
- The integration preserves the completed/cancelled session guard introduced
  in `56df1fa`. Tests additionally cover discharged sessions and failed edits.
- API validation now rejects unknown PATCH fields and explicit null session
  numbers with 422. Clients relying on silently ignored fields must be updated.
- All these clinical commands acquire a parent-treatment database write lock
  before validation and refresh previously loaded ORM state. The lock remains
  held through the audit commit. Real, independent SQLite connections test
  overlapping plan/start, administration CRUD/completion and documentation/
  completion commands, stale objects and release after rollback.
- Lock contention/serialization failures return HTTP 409, without automatic
  replay. Clients must reload current state before retrying. Other database
  errors are not mislabeled as concurrency conflicts.
- Successful completion now stores one versioned evidence record containing the
  session, treatment/protocol snapshot, planned components, full administrations,
  material identities/lot requirements, actor attribution and the pre-transition
  completion decision. Referenced catalog rows are locked in deterministic order
  during the guard and capture. Evidence and the existing transition audit commit
  atomically; that audit includes the evidence checksum.
- `GET /api/v1/treatment-sessions/{id}/finalization` reads stored evidence only,
  under the existing clinical-summary read roles. Missing evidence returns 404
  (including legacy completed sessions); corrupt/unsupported evidence returns
  409. There are no create/update/delete evidence endpoints. The original
  clinical-summary endpoint remains a LIVE calculation, not signed evidence.
- Capture occurs on completion, not cancellation or discharge, and is not a
  physician signature. Existing workflow roles are unchanged. Schema version 1
  and `completion-guard-v1` identify the captured format and policy; bump these
  deliberately if their meaning changes. Decimal amounts serialize as strings.
- ORM updates/deletes are refused; an FK restricts deletion of a session with
  evidence. SHA-256 detects accidental/out-of-band changes but is NOT a digital
  signature: privileged SQL can change both data and checksum. No database-wide
  tamper-proof or legal-signature guarantee is claimed.
- Stage 7 adds migration `d9a4c7e2f1b6` and append-only corrections/supplements
  linked to the exact finalization checksum. The original completion evidence is
  never updated. Each amendment contains a standard reason code, required reason
  detail, statement, optional target reference, author snapshot and checksum.
- Admins, physicians and nurses may author amendments. Admins and physicians may
  approve or reject them. Physicians cannot decide their own amendments; admins
  may self-review as explicitly selected for this deployment. Rejections require
  a comment. Operator and viewer roles remain read-only and share the existing
  finalization visibility.
- Amendment content and its single final review are separate immutable records.
  A rejected amendment is retained; correction requires another amendment rather
  than rewriting history. Creation/review and their allowlisted audit events
  commit atomically under the parent-treatment write lock.
- Amendment/review checksums detect accidental or one-sided out-of-band edits but
  are not digital signatures. Privileged SQL can still replace both content and
  checksum. No independent clinical signature, external timestamp, amendment
  notification or legally certified audit store is claimed.
- Stage 8 adds the pinned Psycopg driver and a separate PostgreSQL 18 CI matrix on
  Python 3.12 and 3.14. Each job upgrades a fresh disposable database to Alembic
  head, requires a clean autogeneration check, and exercises real PostgreSQL
  parent-row locks, independent-treatment concurrency, deadlock recovery,
  account table locking and amendment sequencing. Test records are synthetic.
- PostgreSQL connections now set a bounded lock wait through
  `DATABASE_LOCK_TIMEOUT_MS` (default 5000 ms, allowed range 100-30000 ms).
  Recognized PostgreSQL lock timeout, deadlock and serialization failures remain
  controlled conflicts; there is no automatic replay.
- Stage 9 adds migration `e21f6a9c3b40` and persistent login-throttle state on
  each account. Five failures inside a 15-minute observation window lock the
  account for five minutes by default. The three settings are validated and may
  be reviewed per deployment. Correct login or an administrator password reset
  clears the state; active locks are not extended by repeated requests.
- Wrong-password, missing-user, inactive-account and locked-account requests all
  return the same 401 detail. Missing usernames still execute the password hash
  verifier but are not stored. Known-account failures and recovery are recorded
  with allowlisted counts/flags only, never the password, hash, submitted
  username or IP address. Account-lock contention returns a bounded 503 with a
  short `Retry-After`; it is not mislabeled as invalid credentials.
- PostgreSQL uses compatible table intent locks plus a per-account row lock, so
  unrelated logins can progress while same-account counters serialize. SQLite
  necessarily serializes database writers. CI exercises the PostgreSQL behavior;
  intended deployment topology and login load still require validation.

## Remaining engineering gates

Account audit add-on (stage 5): account creation, initial bootstrap and meaningful
updates now commit with allowlisted audit events. Password reset events include
only an action flag and field name, never credentials or hashes. Self-edits keep
pre-change actor attribution. The new admin-only user-history endpoint is
paginated. No-op edits and failed writes do not emit success events; historical
changes are not backfilled. Stage 9 adds future known-account login-failure and
recovery events, but not an alerting pipeline, source/IP telemetry or historical
reconstruction. This is not a tamper-proof database. Stage 5 itself introduced
no schema change.

Token-revocation add-on (stage 6): login tokens carry a per-account version.
Password resets and meaningful role/active-status changes increment that version
in the same account/audit transaction, invalidating all older tokens for that
user. Display-name and no-op edits do not revoke sessions. Legacy tokens without
a version are rejected, so every user must log in again after deployment. This
is not a token inventory, logout endpoint, refresh-token system or replacement
for emergency signing-key rotation. Stage 9 separately adds account-bound login
throttling. Privileged SQL can bypass both controls.

Account safety add-on: last-active-admin demotion/deactivation is refused with
409. Account commands share a database lock with bootstrap and hold it through
commit, refresh cached ORM state and recheck HTTP actors' authority. Tests use
independent SQLite connections for competing admin changes, revoked actors and
commit rollback. Unknown/explicit-null user PATCH fields now return 422. This
stage adds no migration, token revocation or clinical policy change. Service
guards do not protect against direct privileged SQL or legacy unlocked workers.

Runtime safety stage: `ENVIRONMENT=production` rejects debug mode, enabled
public bootstrap and obviously weak/default signing keys. Production disables
interactive API docs/OpenAPI; this is not a substitute for authorization.
Bootstrap is explicitly switchable and SQLite requests are serialized before
the empty-user check. PostgreSQL uses the same account table lock for bootstrap.
That lock primitive is exercised by disposable PostgreSQL CI; concurrent
bootstrap remains covered separately by the SQLite integration test.
JWTs must contain subject, issuance time and expiry. Existing minted tokens have
these fields; older externally minted tokens without them are rejected.
`/health` is liveness only; `/health/ready` checks the expected database revision,
critical tables and SQLite FK enforcement and returns a redacted 503 on failure.
The pinned direct dependencies reflect the tested environment, not a completed
vulnerability audit or full transitive dependency lock.

1. Concurrency deployment gate: CI now exercises the parent-lock protocol on a
   disposable PostgreSQL 18 instance at `READ COMMITTED`, including bounded lock
   waits, a real deadlock, same-parent serialization and unrelated-parent
   progress. This is not load, failover, connection-pool or managed-service
   certification; repeat the tests against the intended production topology and
   reviewed timeout. SQLite still serializes all database writers. Review
   database triggers/CDC because no-op parent updates can invoke them. Model
   `updated_at` is explicitly preserved. Direct SQL, catalog changes and legacy
   services are not protected by this service protocol. A rolling deployment
   with old unlocked workers is unsafe:
   drain old workers before accepting clinical writes with this version.
2. Historical evidence next gate: append-only amendments are implemented, but
   historical sessions without captured finalization evidence are deliberately
   not backfilled because their completion-time state cannot be proven. Define
   independent clinical-signature requirements, notification/escalation rules,
   retention, database permissions and external integrity anchoring before making
   stronger legal or tamper-proof claims.
3. Clinical policy: define no-administration session outcomes, expiry checks,
   deviation acknowledgments and physician override reasons. These policies
   need explicit clinical sign-off before implementation and use.
4. Security/operations: persistent known-account login throttling is implemented,
   but source/IP and edge throttling, alert delivery, incident response and audit
   retention remain deployment responsibilities. Replace development secrets,
   review authentication/bootstrap exposure, and configure HTTPS, backups,
   restore testing, monitoring and access control. Do not expose development
   defaults.
5. Product scope: define the first release's mobile-friendly user interface,
   roles, deployment environment and acceptance scenarios.

## Migration cautions

The new head is `e21f6a9c3b40`, following `d9a4c7e2f1b6`. It adds three
login-throttle columns to `users`; existing accounts start with a zero counter
and no lock. The preceding migration adds empty `session_amendments` and
`session_amendment_reviews` tables without reconstructing historical records.
Existing clinical records are untouched. Drain old workers, upgrade the
database, then deploy only new code. A mixed-version fleet is unsafe because old
workers ignore the new lock state.
A mixed-version fleet is unsafe: new code rejects old tokens and old code neither
mints nor enforces the version claim.
Back up and rehearse on a disposable copy before any production upgrade.

The amendment downgrade refuses when any pending, approved or rejected amendment
exists. Its offline downgrade is also refused. Never delete clinical amendment
history to bypass that guard. The auth-version downgrade refuses when any account
has a non-zero version,
because removing it could restore revoked sessions under old code. Its offline
downgrade is also refused. Rotate the signing key and use an approved recovery
procedure rather than bypassing that guard. The evidence downgrade refuses if
any finalization evidence exists; offline
downgrade is also refused because evidence cannot be checked. An empty-table
downgrade is tested. Do not bypass the guard by deleting evidence. Downgrading
below `c68b24017654` still deletes administration records. Never use downgrade as
a production rollback without an approved recovery plan. Ephemeral PostgreSQL
CI is not certification of a production database service. Session/parent
deletion may now fail with an FK
restriction; retention and deletion UX require explicit design.

The login-throttle downgrade refuses while any account has a failure counter,
window or lock timestamp, and refuses offline downgrade because that state cannot
be checked. Do not clear security state merely to force a downgrade; use the
reviewed password-reset/recovery path and a controlled deployment plan.

## Developer verification

Run from the repository root in an isolated environment:

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest backend/tests -q
```

The test suite uses disposable databases. Production migrations and deployments
are separate controlled operations, not part of the test commands.

Pull requests into `main` and pushes to `main` also run the read-only `Backend
CI` workflow on Python 3.12 and 3.14. The SQLite matrix compiles the backend,
upgrades a fresh database, runs `alembic check`, and executes the complete suite.
A second matrix upgrades a fresh PostgreSQL 18 database and runs the dedicated
PostgreSQL integration tests. The stable `Backend CI` summary succeeds only when
all four matrix jobs succeed and is the status check intended for branch
protection. The workflow receives no repository secrets, has only `contents:
read` permission, and never targets production data.
