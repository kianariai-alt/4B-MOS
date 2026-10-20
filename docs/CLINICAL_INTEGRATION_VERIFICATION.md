# Clinical Integration — verification record

Current verification: 20 October 2026. Scope: synthetic records only. No clinic
database, live imaging center, remote model, deployment, force push or main merge.

## Audited baseline and delivery

- main: `bc6fb3f15825d6eaccaa45503ad61a432baf1c5b`.
- Existing integration PR [#44](https://github.com/kianariai-alt/4B-MOS/pull/44),
  branch `feature/clinical-intelligence-integration`, was already implemented at
  `abb60d24f79efe498a19faaa9d7bc16967061ef7`. This round extends that implementation.
- PR [#43](https://github.com/kianariai-alt/4B-MOS/pull/43) was open, draft and
  unmerged at `3fafc6224d17209ee47373aede4bf9dedfa76a72`. Its six files and Persian
  design document were reviewed; none were imported or rewritten.
- Contract/review/coverage hardening:
  `42400424e33caa9144dae93426b33a26e60c4e62`.
- Read-only snapshots, optional decision contract, guarded mocks, prototype and
  handoff: `61cc8455161c5c7d8cace15f253a384a6441f29a`.
- This verification update changes documentation only. The PR's checks identify
  the exact delivered head and the authoritative current CI result.

## Actual local results

Python 3.12.14, isolated virtual environment, repository runtime/dev requirements.

- **Complete backend suite: 853 passed, 19 skipped, 6 warnings, exit 0,
  318.12 seconds.** All 19 skips require disposable PostgreSQL, unavailable
  locally. They are not counted as passes.
- Related modules within that run: 26 contract cases, 27 existing persisted
  integration API cases, 43 decision/mock cases, 21 read-only snapshot cases
  and one migration case: **118 passed** in total.
- Warnings: existing Starlette/httpx deprecation and Python 3.12 SQLite datetime
  adapter deprecations. No dependency was changed to silence them.
- `compileall` on the complete backend passed.
- OpenAPI generation includes the independent read-only
  `GET /api/v1/visits/{visit_id}/clinical-intelligence`.
- All three published JSON Schemas match their Pydantic contracts.
- Existing two-core sample parses as `DecisionSupportResult`.
- Fixed three-mock knee/MRI sample equals the executable
  `synthetic_snapshot()` output, including its semantic digest, byte-independent
  model round-trip and non-diagnostic flags.
- Baseline-to-patch whitespace checks and new source trailing-whitespace checks
  passed. Repository files were obtained at the immutable baseline via GitHub
  when direct shell cloning was unavailable; unchanged baseline blob hashes
  were checked during reconstruction.

The sandbox denies sends on asyncio's local wakeup socket, causing ordinary
Starlette TestClient startup to hang before requests. Actual local API tests used
a **scratch-only runner** that caps selector waits at 1 ms; this allows queued
cross-thread callbacks to execute. It changes no application, transport, test
assertion, database, installed dependency or network permission. The runner is
outside the repository and is not delivered. CI runs normal pytest unchanged.

## Scenarios verified

Missing imaging; verified and administrator-finalized/unverified reports;
draft, rejected and invalid lifecycle contract states; same-code/site
contradiction; source/model/hash changes; missing or retired knowledge;
unresolved Safety alerts; adapter corruption/timeout/expiry/omission; malformed
contracts; forbidden and unauthenticated access; safe database failure; concurrent
dependency and ordinary Safety review changes; stable repeated GET hashes;
no SQL writes from GET; exact-fixture-only mock guards; model outputs never
promoted to confirmed findings, treatment authorization or clinical clearance.

## Migrations and remaining limits

No new migration was added in this round. The existing proposed migration
`b12f6c8d4a90` was exercised on disposable SQLite: upgrade from the prior revision,
metadata check, preservation of synthetic legacy rows, empty downgrade/re-upgrade,
and refusal to discard persisted evidence all passed. No operational migration
was executed. PostgreSQL upgrade/concurrency checks remain covered by the
existing CI harness and must be assessed at the delivered commit.

The API is disabled by default with `CLINICAL_INTEGRATION_ENABLED=false`.
Actual specialist inference, authorized DICOM identity and quality, clinical
freshness policy, authenticated model-specific review transport, external model
validation and clinician UI remain separate workstream dependencies. The local
report review inventory attests only to source-record finalization.

Snapshot SHA-256 is the documented **semantic digest**, excluding GET observation
and passthrough read times; persisted Run hashes retain separate full-payload
semantics. Neither is a signature or a guarantee of clinical validity.
See [contract](contracts/unified-clinical-data-v1.md),
[Persian handoff](CLINICAL_INTELLIGENCE_HANDOFF_FA.md), and
[architecture](CLINICAL_INTELLIGENCE_INTEGRATION.md).
