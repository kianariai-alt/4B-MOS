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

## Remaining engineering gates

Account audit add-on (stage 5): account creation, initial bootstrap and meaningful
updates now commit with allowlisted audit events. Password reset events include
only an action flag and field name, never credentials or hashes. Self-edits keep
pre-change actor attribution. The new admin-only user-history endpoint is
paginated. No-op edits and failed writes do not emit success events; historical
changes are not backfilled. This is not login/failed-attempt monitoring, token
revocation or a tamper-proof database. No schema change is introduced.

Token-revocation add-on (stage 6): login tokens carry a per-account version.
Password resets and meaningful role/active-status changes increment that version
in the same account/audit transaction, invalidating all older tokens for that
user. Display-name and no-op edits do not revoke sessions. Legacy tokens without
a version are rejected, so every user must log in again after deployment. This
is not a token inventory, logout endpoint, refresh-token system, rate limiter or
replacement for emergency signing-key rotation. Privileged SQL can bypass it.

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
the empty-user check. PostgreSQL uses a table lock for bootstrap but is untested.
JWTs must contain subject, issuance time and expiry. Existing minted tokens have
these fields; older externally minted tokens without them are rejected.
`/health` is liveness only; `/health/ready` checks the expected database revision,
critical tables and SQLite FK enforcement and returns a redacted 503 on failure.
The pinned direct dependencies reflect the tested environment, not a completed
vulnerability audit or full transitive dependency lock.

1. Concurrency deployment gate: test the parent-lock protocol on the intended
   production database, including isolation level, lock timeout and load. The
   SQLite implementation serializes all database writers, even for different
   treatments. The no-op UPDATE is intended to lock one parent row on PostgreSQL;
   PostgreSQL has not been exercised here. Review database triggers/CDC because
   no-op updates can still invoke them. Model updated_at is explicitly preserved.
   Direct SQL, catalog changes and legacy services are not protected by this
service protocol. A rolling deployment with old unlocked workers is unsafe:
   drain old workers before accepting clinical writes with this version.
2. Historical evidence next gate: define append-only amendments with original
   evidence reference, author, reason, timestamp and authorized review. No
   amendment or signature workflow exists yet. Historical sessions are not
   backfilled because their original completion-time data cannot be proven.
   Assess database permissions, backups and external integrity anchoring before
   making stronger immutability/retention claims.
3. Clinical policy: define no-administration session outcomes, expiry checks,
   deviation acknowledgments and physician override reasons. These policies
   need explicit clinical sign-off before implementation and use.
4. Security/operations: replace development secrets, review authentication and
   bootstrap exposure, configure HTTPS, backups and restore testing, monitoring,
   access control and retention policy. Do not expose development defaults.
5. Product scope: define the first release's mobile-friendly user interface,
   roles, deployment environment and acceptance scenarios.

## Migration cautions

The new head is `b36e7f0a1d42`, following `a71d92cfe604`. It adds non-null
`users.auth_version` with a zero default; existing clinical records are
untouched. Drain old workers, upgrade the database, then deploy only new code.
A mixed-version fleet is unsafe: new code rejects old tokens and old code neither
mints nor enforces the version claim.
Back up and rehearse on a disposable copy before any production upgrade.

The auth-version downgrade refuses when any account has a non-zero version,
because removing it could restore revoked sessions under old code. Its offline
downgrade is also refused. Rotate the signing key and use an approved recovery
procedure rather than bypassing that guard. The evidence downgrade refuses if
any finalization evidence exists; offline
downgrade is also refused because evidence cannot be checked. An empty-table
downgrade is tested. Do not bypass the guard by deleting evidence. Downgrading
below `c68b24017654` still deletes administration records. Never use downgrade as
a production rollback without an approved recovery plan. SQLite testing is not
PostgreSQL certification. Session/parent deletion may now fail with an FK
restriction; retention and deletion UX require explicit design.

## Developer verification

Run from the repository root in an isolated environment:

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest backend/tests -q
```

The test suite uses disposable databases. Production migrations and deployments
are separate controlled operations, not part of the test commands.

Pull requests into `main` and pushes to `main` also run the read-only `Backend
CI` workflow on Python 3.12 and 3.14. Each matrix job installs the pinned
requirements, compiles the backend, upgrades a fresh disposable SQLite database,
runs `alembic check`, and executes the complete backend test suite. The stable
`Backend CI` summary job succeeds only when every matrix job succeeds and is the
status check intended for branch protection. The workflow receives no repository
secrets, has only `contents: read` permission, and never targets production data.
