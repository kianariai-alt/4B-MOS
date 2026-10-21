# Clinical core handoff — actual verification record

This additive follow-up is based on integration PR44 at
`8129085ffea310a62778fa2c8b87f47a198d0956`. Its implementation commit is
`d5d6cabf4f0198d2c401e111cc7e8ad76e44063a`. No pre-existing integration file was
modified; producer implementations and medical content are absent from the
delivery branch. They are read only from pinned exports/checkouts into a fresh
disposable test directory.

## Actual local results

Python 3.12.14; full independent and composed runs executed concurrently using
synthetic in-memory SQLite fixtures and disposable migration databases.

| Run | Actual result | Duration |
| --- | --- | --- |
| Integration proposal, complete backend suite | **921 passed, 19 skipped, 6 warnings**, exit 0 | 453.33 seconds |
| Disposable integration + imaging + orthopedic composition | **1020 passed, 19 skipped, 6 warnings, 13 subtests passed**, exit 0 | 466.85 seconds |
| New composer/report consumer unit cases | **68 passed**, one existing warning | 2.08 seconds |
| Actual pinned producer/consumer handoff cases | **16 passed**, one existing warning | 3.79 seconds |

All 19 skips in each full run require disposable PostgreSQL. No PostgreSQL
composition is claimed locally. The existing six warnings concern Starlette's
httpx adapter and Python 3.12's SQLite datetime adapter.

Compilation, workflow YAML parsing, exact reproduction of the checked-in
digest-only receipt, and a direct non-blocking FIFO rejection check passed.
The composed tree preserves all protected integration source bytes. Every
specialist source/artifact Git blob matches the audited manifest.

## What the tests establish

- The actual imaging adapter runs against the current strict unified contract,
  preserves source values and cannot authenticate physician review. Changed
  Study/Series, binding or clinical presence invalidates its component or blocks
  output. Saved-run freshness and read-only API behavior are exercised.
- The actual orthopedic producer reproduces its retained fixture exactly. Its
  real published JSON Schema and result digest validate. Its 27 Draft evidence
  references cannot become Integration's approved KnowledgeReference, and its
  preview cannot become CoreOutput or a clinical decision.
- The composer rejects wrong revisions, changed file hashes, symlinks,
  traversal, overwrite attempts and existing destinations before publishing
  a disposable test tree. Consumer JSON is bounded, duplicate/non-finite values
  are rejected, and nonlocal schema references are forbidden.
- Unit tests deliberately use a no-op schema validator to test independent
  consumer guards without making optional dependencies mandatory. The real
  producer tests use real jsonschema; the no-op unit fixture is not a fallback
  validator and is not used by the executable tool or compatibility workflow.

## Exact local dependency provenance and sandbox limits

Runtime/dev dependencies are the existing backend requirements. Optional
compatibility versions are pydicom 3.0.1 and jsonschema 4.26.0. pydicom's 82
official source/resource blobs were obtained at
`50cd981a068c74b01d854c6cac9bb897fe0b74a9`; all Git blob hashes were checked.
Only normal scratch distribution metadata declaring the official name/version
was generated for source import. No library source was changed or stubbed.
The local compatibility environment reuses the existing integration environment
and system jsonschema through Python site paths. These scratch files are not
part of the delivery. CI installs the pinned optional packages normally.

The managed sandbox denies asyncio wakeup-socket sends. The local scratch test
runner caps selector waits at 1 ms so actual TestClient requests can execute.
No application code, transport, assertion or test database is changed. This
runner is outside the repository; CI runs ordinary pytest.

Local source trees were immutable Connector exports, so the composer explicitly
recorded `git_revisions_verified=false` and `integration_revision=null`, while
checking all specialist file hashes. This is distinct from CI's required exact
Git HEAD checks and integration-base ancestry check.

## CI and delivery scope

The new workflow runs independent and composed suites on Python 3.12 and 3.14
and retains digest-only receipts. Its actual result must be read from the new
PR's checks at the delivered head, not inferred from older PR43/44/46 checks.
The implementation is a separate stacked proposal targeting
`feature/clinical-intelligence-integration`.

No specialist code is enabled in the API. No Registry facts, patient database,
operational migration, external imaging-center connection, model weights,
deployment, force push or main merge were used. Software compatibility does
not establish DICOM identity, specialist review, source-document integrity or
clinical validity. Remaining coordination is documented in the
[Persian handoff](CLINICAL_CORE_HANDOFF_COMPATIBILITY_FA.md).
