# Clinician Decision & Learning Feedback Loop

Stage 20 closes the provenance loop between a transparent treatment-options
roadmap, the physician's actual decision, treatment execution and later outcomes.

The system still does not select treatment. A decision record exists only after
an authenticated physician explicitly submits it.

## Decision endpoints

- `POST /api/v1/visits/{visit_id}/treatment-decisions`
- `GET /api/v1/visits/{visit_id}/treatment-decisions`
- `GET /api/v1/treatment-decisions/{decision_id}`
- `GET /api/v1/treatment-decisions/{decision_id}/audit-logs`

Only an active physician may create a decision. Admin, physician and nurse roles
may read the immutable decision history.

## Decision types

A physician can record:

- selection of one exact roadmap option;
- modification of one roadmap option;
- combination of two or more roadmap options;
- selection of one active protocol outside the roadmap;
- deferral of a treatment decision;
- no treatment at the current stage.

The API validates the shape of each decision. A direct selection must reference
exactly one protocol currently present in the exact roadmap snapshot. A combined
decision must reference at least two roadmap options. A protocol outside the
roadmap must be an exact active code/version and is permitted only after the
current safety workflow is complete.

## Exact snapshot binding

Every new decision binds to:

- the current clinical-context SHA-256;
- the exact treatment-options-roadmap SHA-256;
- the full roadmap snapshot shown at decision time, including cohort definitions,
  aggregate option metrics, source outcome hashes and stated limitations;
- any selected protocol code/version/treatment type;
- the hashes of any current-context evidence briefs explicitly cited;
- the authenticated physician;
- the prior decision hash when this decision supersedes another decision.

If the clinical context, roadmap or prior decision changes before submission,
the write is rejected and the physician must reload.

## Append-only decision lineage

Decisions are never edited or deleted through the ORM.

When the physician changes course, the new decision stores the identifier and
SHA-256 of the previous decision. The earlier record remains intact and becomes
historical.

The supersession identifier is intentionally a logical lineage reference rather
than a database self-foreign-key. Chain integrity is verified against the prior
immutable row and its SHA-256 before a new decision is accepted; this keeps the
same lineage semantics across the supported SQLite and PostgreSQL environments.

This means later analysis can distinguish what the physician believed at each
decision point rather than reconstructing history from a mutable current field.

## Treatment execution link

`TreatmentCreate` now accepts an optional
`source_treatment_decision_id`.

When supplied, treatment creation is serialized by the same visit-level clinical
write lock and verifies that:

- the decision belongs to the same visit;
- the decision is still current;
- the clinical context has not changed since that decision;
- the decision is actionable rather than `defer` or `no_treatment`;
- the exact active protocol used for treatment appears in that decision.

The Treatment row freezes both:

- `source_treatment_decision_id`
- `source_treatment_decision_sha256`

Those fields automatically enter session-finalization evidence because
finalization freezes the full Treatment snapshot.

## Outcome feedback link

The existing outcomes registry freezes the full Treatment snapshot in each
outcome payload. Therefore an outcome associated with a decision-linked
Treatment is transitively and cryptographically traceable to the physician
decision that preceded execution.

Decision reads expose the identifiers of linked Treatments and linked Outcomes,
creating a simple auditable loop:

Roadmap → Physician Decision → Treatment → Finalization → Outcome.

## Interpretation

This feedback loop does not automatically promote, demote or rewrite a protocol
because of one outcome or a small set of outcomes.

Outcome observations remain subject to confounding, selection bias, missing
follow-up and measurement limitations. They become input to the separate,
transparent similar-patient cohort process only under that process's minimum
cohort and reproducibility rules.

The system does not transform physician choices into autonomous treatment
policy.
