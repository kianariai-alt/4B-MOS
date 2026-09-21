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
- Stage 10 adds a public-HTTP API acceptance gate using only synthetic records in
  the disposable test database. Separate operator, physician, nurse, reviewer
  and viewer credentials exercise registration, protocol-linked planning,
  administration traceability, completion checks, immutable finalization,
  append-only amendment approval, discharge, summaries, timeline and audit
  history as one coherent journey. A companion OpenAPI contract check protects
  release-critical paths and operation-ID uniqueness. This adds no migration or
  clinical policy and is not production, UI or clinician acceptance testing.
- Stage 11 adds a redacted, read-only release preflight shared with the HTTP
  database-readiness definition. It requires production runtime mode, the exact
  Alembic head and critical tables, enabled SQLite foreign keys when applicable,
  and at least one active administrator. It returns only fixed result codes and
  never prints database URLs, exception messages, credentials, identities or
  clinical records. It performs no migration, account creation or deployment.
- Stage 12 adds a minimal backend container image with runtime-only dependencies,
  a numeric non-root user and a readiness health check. CI migrates a disposable
  SQLite volume, starts the image in production mode with all capabilities
  dropped, `no-new-privileges` and a read-only root filesystem, then verifies
  health/readiness and disabled production docs. Normal image startup never runs
  migrations. This creates an artifact and smoke gate, not a hosted deployment,
  registry attestation, vulnerability certification or infrastructure approval.
- Stage 13 adds a Persian, mobile-friendly staff console at `/app/` for the
  existing login, live-flow projection and backend-authorized workflow actions.
  Access tokens remain memory-only, assets are same-origin and non-cacheable, and
  restrictive browser headers are applied. CI validates JavaScript syntax and
  loads the console from the hardened container. This adds no clinical policy,
  migration, offline data store, patient portal, deployment or human acceptance.
- Stage 14 adds migration `f4b14c2d9a01` and a source-linked, versioned medical
  knowledge registry. Admins and physicians may author drafts; a different active
  admin or physician must approve or reject them. Approved replacements retire
  the previous approved version atomically. All reads verify a canonical SHA-256,
  and lifecycle events are audited. The consumer endpoint exposes only approved,
  currently valid facts. SHA-256 is integrity detection, not a signature. No
  publications are bundled, no patient data is converted into knowledge, and no
  recommendation or autonomous-learning engine is claimed.
- Stage 15 adds migration `a8c15d3e7b02`, a structured clinical-intake lineage
  per visit and versioned paraclinical-report lineages with typed atomic
  observations. Only current final records appear in the aggregate clinical
  context. Final content is immutable through the API; corrections are new
  reason-linked drafts whose finalization atomically supersedes the prior final.
  Entered-in-error records remain retained but are excluded from current context.
  All content reads verify canonical SHA-256 values, and audit metadata avoids
  duplicating clinical text or values. The format is FHIR-inspired but not
  FHIR-conformant; submitted terminology and UCUM-style units are not validated
  by a terminology server. No recommendation or autonomous learning is added.
- Stage 16 adds migration `c92e4b7a1d30`, governed versioned clinical-safety
  rules linked to approved current medical-knowledge facts, and append-only visit
  evaluation snapshots. A bounded declarative schema rejects executable or
  unknown predicates. Independent review controls approval and supersession;
  evaluations consume only current final context, capture rule/context/result
  hashes, citations and condition traces, and fail closed when linked evidence
  becomes unavailable. `no_alerts` and `no_active_rules` explicitly remain
  non-clearance outcomes. No rule content, diagnosis, prescription, treatment
  ranking, autonomous learning or clinician-facing advice UI is bundled.
- Stage 17 adds migration `d51e7a9b2c64` and append-only, hash-chained review
  events for safety findings. Physicians and nurses can acknowledge or escalate;
  only physicians can record a terminal assessment for that immutable snapshot.
  Optimistic evaluation hashes and the visit lock reject stale or competing
  writes. Review notes are excluded from minimized audit metadata. Every response
  remains non-clearance and review events never mutate, dismiss or override the
  original evaluation. Notification delivery, alert-fatigue policy, override
  authority and the clinician-facing UI were not part of that stage; Stage 20
  now adds only the bounded workflow surface while the other items remain open.
- Stage 18 adds migration `e6b7c8d9a401` and immutable, physician-selected
  evidence briefs linked to one exact final clinical-context snapshot and one
  through twenty approved current knowledge facts. Context and fact hashes fail
  stale creation closed; full source/fact snapshots and explicit limitations are
  retained, while audit metadata excludes the clinical question, patient values
  and evidence statements. Deterministic fact order is not ranking. Every output
  remains non-recommendation, non-risk-score, non-clearance, non-time-critical
  and requires independent physician review. No automatic matching, diagnosis,
  treatment direction, publication ingestion or learning is added.
- Stage 19 adds no migration. It extends the same-origin Persian console with a
  role-gated evidence workspace: admins and nurses can read, while only an active
  physician can manually select one through twenty approved facts and create a
  brief. The current-context response now includes the server-calculated digest
  used by the existing optimistic create guard. The browser preselects nothing,
  treats fact-key order as non-ranking, renders source URLs as inert text, stores
  no token or patient data offline and exposes no edit/delete path. This is a UI
  engineering gate, not clinician acceptance, recommendation logic or a
  regulatory determination.
- Stage 20 adds no migration. It adds a role-gated clinical safety inbox to the
  same-origin console and a read-only aggregate endpoint for the latest verified
  evaluation, context freshness and verified finding-review timelines. Admins,
  physicians and nurses can read; admins/physicians can run an evaluation;
  physicians/nurses can acknowledge or escalate; only physicians can assess.
  Optimistic hashes, append-only history and backend roles remain authoritative.
  The UI has no dismiss, override, delete, clearance or treatment-authorization
  action and adds no recommendation, notification or automatic learning.
- Stage 21 adds no migration. It adds a role-gated cross-visit queue derived from
  complete, verified finding-review chains whose latest event is `escalated`.
  The bounded response exposes minimum routing metadata, omits notes and
  condition traces, preserves stale-context visibility and fails the entire read
  closed if any stored chain is corrupt. Physician assessment removes an item
  from the open view without deleting history. Oldest-first ordering is
  administrative, not clinical priority. No external delivery, assignment,
  response-time enforcement, recommendation, clearance or learning is added.

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
   deviation acknowledgments, safety-alert response times and physician override
   authority. The append-only finding-review record and Stage 21 chronological
   queue do not implement priority, deadlines or an override. These policies need
   explicit clinical sign-off before use.
4. Security/operations: persistent known-account login throttling is implemented,
   but source/IP and edge throttling, alert delivery, incident response and audit
   retention remain deployment responsibilities. Replace development secrets,
   review authentication/bootstrap exposure, and configure HTTPS, backups,
   restore testing, monitoring and access control. Do not expose development
   defaults.
5. Product scope: the backend now has a synthetic API-level acceptance scenario,
   a mobile-friendly staff console for live clinic flow, physician-selected
   evidence snapshots and the deterministic safety/review workflow, including a
   same-origin open-escalation queue. Define external notification delivery,
   response-time/alert-fatigue policy, broader
   clinical advice scope, terminology service, deployment environment, clinical
   ownership and human acceptance scenarios before use.

## Migration cautions

The new head is `e6b7c8d9a401`, following `d51e7a9b2c64`. It adds an empty
`clinical_evidence_briefs` table and does not select evidence or create a brief
for any existing visit. The preceding review revision adds an empty
`clinical_safety_finding_reviews` table and does not create, acknowledge or
assess any finding. The preceding safety revision adds empty
`clinical_safety_rules`, `clinical_safety_rule_knowledge`,
`clinical_safety_evaluations` and `clinical_safety_findings` tables. No rules or
medical claims are seeded and no existing patient record is evaluated during
either migration. The preceding structured-context revision adds empty
`clinical_intakes`, `paraclinical_reports` and `paraclinical_observations`
tables; no record is inferred or backfilled from legacy free text. The preceding
registry migration adds empty `medical_knowledge_facts` and
`medical_knowledge_sources` tables; no medical claims are seeded and existing
clinical records are untouched. Earlier migrations add persistent login-throttle
state and empty amendment history tables. Drain old workers, upgrade the database,
then deploy only new code. A mixed-version fleet is unsafe because old workers
neither enforce the registry or structured-record workflows nor expect the new
schema revision.
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

The medical-knowledge downgrade refuses if any fact or source exists and refuses
offline downgrade because registry contents cannot be checked. Never delete or
rewrite reviewed knowledge merely to force a rollback; restore the reviewed
release/database pair through the controlled recovery process.

The structured-context downgrade refuses if any intake, report or observation
exists and refuses offline downgrade because patient content cannot be checked.
Do not delete patient documentation to force a rollback. Restore the reviewed
application/database pair and reconcile through an approved recovery process.

The clinical-safety downgrade refuses if any rule, evidence link, evaluation or
finding exists and refuses offline downgrade. Do not delete governed rule or
evaluation history to force a rollback. Restore the reviewed application and
database pair and use the clinical governance recovery process.

The finding-review downgrade refuses if any review event exists and refuses
offline downgrade. Do not delete review history or break its hash chain to force
a rollback. Restore the reviewed application/database pair and follow the
approved clinical governance recovery process.

The clinical-evidence-brief downgrade refuses if any brief exists and refuses
offline downgrade. Do not delete physician-selected evidence history to force a
rollback; restore the reviewed application/database pair through the approved
clinical governance recovery process.

## Developer verification

Run from the repository root in an isolated environment:

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest backend/tests -q
```

The release-critical cross-module scenario can also be run directly with
`python -m pytest backend/tests/test_release_acceptance.py -q`; see
`docs/RELEASE_ACCEPTANCE.md` for its coverage and explicit limitations.

After upgrading the selected release database and completing isolated initial
administrator setup, run `python -m backend.tools.release_preflight` with the
reviewed private production environment. A zero exit status is a technical
prerequisite only. See `docs/RELEASE_PREFLIGHT.md` for ordering, fixed result
codes and limitations.

The test suite uses disposable databases. Production migrations and deployments
are separate controlled operations, not part of the test commands.

Pull requests into `main` and pushes to `main` also run the read-only `Backend
CI` workflow on Python 3.12 and 3.14. The SQLite matrix compiles the backend,
upgrades a fresh database, runs `alembic check`, and executes the complete suite.
A second matrix upgrades a fresh PostgreSQL 18 database and runs the dedicated
PostgreSQL integration tests. A container job also builds and starts the release
image against a disposable migrated database under the hardened runtime contract.
The stable `Backend CI` summary succeeds only when all four matrix jobs and the
container smoke succeed and is the status check intended for branch protection.
The workflow receives no repository secrets, has only `contents: read`
permission, and never targets production data.
