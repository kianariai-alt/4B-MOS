# Medical knowledge registry

Stage 14 establishes the governed knowledge layer required before 4B-MOS can
support clinician-facing decision support. It stores evidence statements and
their sources; it does not itself diagnose, prescribe, rank therapies, or learn
from patient records.

## Safety contract

- Every fact has at least one explicit source and a reproducible canonical
  SHA-256 over its content, validity window and ordered source list.
- New content begins as `draft`, moves to `in_review`, and needs a decision from
  a different active admin or physician. An author cannot review their own fact.
- Rejected facts remain retained and may be revised and resubmitted. Approved
  content is immutable through the API.
- An approved fact is revised only through a new `supersede` version. Approving
  that version retires the previous approved version in the same transaction.
- Consumer reads return only `approved` facts whose `valid_from`/`valid_to`
  interval contains the requested date.
- Every controlled lifecycle mutation has an audit event. Direct privileged SQL
  remains outside the service guard; the hash detects one-sided changes but is
  not a digital signature or an external timestamp.

No initial clinical claims are seeded. Production content must be entered or
imported from reviewed publications and independently approved. Patient cases,
outcomes and staff notes must never silently become general medical knowledge.

## Roles

| Action | Roles |
| --- | --- |
| Read registry / approved facts | admin, physician, nurse, operator, viewer |
| Create, edit, submit, supersede | admin, physician |
| Approve, reject, retire | admin, physician, with independent reviewer rule |
| Read fact audit history | admin, physician, nurse |

## API

All paths are below `/api/v1/knowledge/facts` and require authentication.

| Method and path | Purpose |
| --- | --- |
| `POST /` | Create version 1 as a source-linked draft |
| `GET /` | Search/filter all lifecycle states for governance |
| `GET /approved` | Read only approved facts valid on `as_of` |
| `GET /{fact_id}` | Read one version and verify its integrity |
| `PATCH /{fact_id}` | Edit a draft or rejected version |
| `POST /{fact_id}/submit` | Move a draft to independent review |
| `POST /{fact_id}/review` | Approve or reject an in-review version |
| `POST /{fact_id}/supersede` | Create the next draft from an approved version |
| `POST /{fact_id}/retire` | Retire an approved version without replacement |
| `GET /{fact_id}/audit-logs` | Read its ordered lifecycle history |

Supported therapy labels currently match the project scope: `PRP`, `PRGF`,
`ACS`, `PL`, `SVF`, `EXOSOME`, and `MSC`. A fact may also omit `therapy_type`
when it is general clinical knowledge. Evidence grades are explicit metadata,
not a computed appraisal: `high`, `moderate`, `low`, `very_low`, `consensus`, or
`ungraded`.

## Controlled deployment

1. Drain older workers and back up the selected database through the existing
   recovery procedure.
2. Rehearse `alembic upgrade head` on a disposable restored copy. The expected
   head is `f4b14c2d9a01`.
3. Deploy only the matching application build and run the read-only preflight.
4. Create content with synthetic/staging data first; verify author/reviewer
   separation, approved filtering, superseding and audit history.
5. Obtain clinical governance approval for source selection, evidence grading,
   review cadence, expiry policy and production database privileges before any
   patient-facing or clinician-recommendation use.

Downgrade is refused while either registry table contains data. Do not erase
reviewed knowledge to bypass this protection.

## Explicitly deferred

- structured paraclinical intake and normalization;
- deterministic contraindication/red-flag rules;
- patient-specific recommendation generation with source citations;
- publication surveillance and proposed knowledge updates;
- outcome aggregation, bias monitoring and clinician-approved learning.

Those stages must consume approved registry content and preserve physician
control. They must not train on or promote individual patient records by default.
