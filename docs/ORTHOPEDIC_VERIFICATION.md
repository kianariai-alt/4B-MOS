# Orthopedic authoring preview verification

Verification date: 2026-10-20. This report concerns synthetic software tests and
source traceability, not independent medical approval or clinical validation.

## Delivered artifacts

- Knee pack: 27 Draft propositions, **0 Approved**, 16 source records (13 full
  text, 2 abstracts, 1 bibliographic record); source-specific limitations retained.
- 10 sourced concept relations, 5 unranked differential definitions, 2
  examination definitions, 10 treatment-evidence records, 22 Draft questions.
- Pack manifest SHA-256:
  `e2c417280f15f76bb69555521deceff4aa550b98f9a1f6d1294a25a9e64f7879`.
- Registry-backed explicit Draft importer; no startup import, migration,
  operational safety activation, patient access, or new dependency.
- Additive adapter and three exported JSON Schemas, synthetic example and
  offline demo. Existing shared Integration/Imaging contracts are unchanged.

## Tests and checks

The focused tests cover Registry import idempotency/preflight conflicts,
author permissions, malformed/duplicate/unresolved references, metadata binding,
content/manifest hashes, exported Schema consistency, context/rule provenance,
eight synthetic clinical scenarios, typed answers, missing/conflicting/unclear
data, source separation, unknown/decline handling, API authorization and disabled
defaults, no-store responses and absence of clinical writes. Additional review
tests exercise nested mutation and forged unreviewed imaging.

```bash
ENVIRONMENT=test DATABASE_URL=sqlite:// python -m pytest \
  backend/tests/test_orthopedic_knowledge.py \
  backend/tests/test_orthopedic_questions.py \
  backend/tests/test_orthopedic_adapter.py \
  backend/tests/test_orthopedic_review.py -q
python -m compileall -q backend
python -m backend.tools.orthopedic_knowledge_demo --write-artifacts
git diff --check
```

Focused tests, compilation, schema/demo generation and whitespace checks pass.
The exact full-suite and GitHub CI results, final commit SHA and PR URL are
recorded in the PR delivery report because those results are obtained after this
artifact is committed. The existing Starlette/httpx deprecation warning remains.
Local Python is 3.12.14; PostgreSQL, Python 3.14 and production-container checks
must be read from their actual CI jobs, not inferred from the local SQLite tests.

In this managed executor, restricted-network TestClient runs stalled in AnyIO
portal setup before reaching the API. Repeating with sandbox additional network
permission resolved it; all test data still used an isolated in-memory SQLite
database. No patient database was accessed.

## Remaining dependencies

1. Independent orthopedic review and source currency checks before any approval.
   NICE/ACR Appropriateness direct access was unavailable; OARSI/Cochrane were not
   reviewed in this initial source set. ACS/PL extractions remain abstract-only.
2. Integration team agreement on the additive Draft authoring envelope and
   server-verified mapping from finalized source records. It is not wired into
   the live Physician Copilot or the approved-only Integration knowledge list.
3. Imaging team owns imaging inference and generic decision execution; this
   adapter supplies references only. No model or Bayesian execution is added.
4. Broader anatomy/biomechanics, examinations, validated criteria and additional
   conservative/pharmacological/surgical evidence need further governed packs.
   Empty/unknown evidence fields are not evidence of absence or efficacy.
5. Registry batch import is preflighted and rerunnable, but uses existing
   per-fact commits. It is not an atomic batch transaction.

Main is not modified, and no merge or force push is part of this delivery.
