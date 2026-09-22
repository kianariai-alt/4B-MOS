# Clinical Outcomes Registry

The clinical outcomes registry stores append-only follow-up observations linked
to treatments that were actually administered and have immutable session
finalization evidence.

It is the data foundation for a future transparent similar-patient treatment
options roadmap. It does not currently learn, recommend, rank or select
treatments.

## Recording an outcome

`POST /api/v1/treatments/{treatment_id}/outcomes`

Only an active physician may create an outcome record.

A new record requires:

- a current final structured clinical intake;
- the exact current `clinical_context_sha256`;
- at least one completed treatment session with immutable finalization evidence;
- a follow-up day and observed outcome content.

The record may contain:

- overall status: improved, unchanged, worsened, mixed or unknown;
- patient-reported protocol rating from 1 to 5, documented by the physician;
- physician rating from 1 to 5;
- pain score from 0 to 10;
- a generic function score from 0 to 100;
- named outcome instruments or measurements with explicit scales;
- adverse events;
- clinician notes.

Each outcome freezes:

- the treatment snapshot;
- the current clinical-context hash;
- every completed-session finalization hash available at recording time;
- the protocol code/version when present;
- the outcome payload and its own SHA-256 digest.

Historical outcome rows cannot be updated or deleted through the ORM. A later
follow-up is a new record.

## Read endpoints

- `GET /api/v1/treatments/{treatment_id}/outcomes`
- `GET /api/v1/treatment-outcomes/{outcome_id}`
- `GET /api/v1/treatment-outcomes/{outcome_id}/audit-logs`

Admin, physician and nurse roles may read outcome records.

## Interpretation limits

These records are observational clinical data. They do not establish causation.
Selection bias, confounding, concomitant care, missing follow-up, inconsistent
measurement and small sample sizes can all distort apparent protocol
performance.

Patient and physician ratings are intentionally stored separately. A patient
rating entered in this workflow is explicitly marked as a clinician-documented
patient report, not as a directly authenticated patient submission. The two
ratings must not be merged into a single "success score" without a documented,
validated analysis policy.

Future similar-patient analysis must expose cohort definitions, sample size,
missingness, outcome windows, protocol versions and uncertainty. It must never
silently treat local experience as equivalent to external clinical evidence.
