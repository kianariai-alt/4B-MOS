# Physician Copilot Snapshot

The physician copilot snapshot is a read-only composition endpoint for a single
visit. It gives an authorized physician or administrator one traceable view of
the current structured clinical context, the latest safety inbox, open
escalations from that latest safety evaluation, the visit's immutable
clinician-selected evidence briefs, and immutable longitudinal treatment
outcomes recorded for treatments in that visit.

## Endpoint

`GET /api/v1/visits/{visit_id}/physician-copilot`

Allowed roles:

- `physician`
- `admin`

The endpoint does not write clinical data and does not create a new medical
record.

## Traceability

Every response contains a `manifest` and `snapshot_sha256`.

The manifest binds the response to:

- the current `clinical_context_sha256`;
- the latest safety evaluation result hash, when one exists;
- the latest review hash for each escalation still open in the latest safety
  evaluation;
- every immutable evidence-brief hash for the visit;
- every immutable treatment-outcome hash for the visit.

The snapshot hash is a canonical digest of that manifest and visit identifier.
It is intended for traceability of the assembled view, not as a clinical
signature or authorization.

Evidence briefs whose stored clinical-context hash equals the current context
are also exposed separately as `current_context_evidence_briefs`. Historical
briefs remain visible in `evidence_briefs` and are never silently rewritten.

## Safety boundaries

The copilot snapshot:

- does not diagnose;
- does not recommend, rank or select treatments;
- does not calculate a patient risk score;
- does not grant clinical clearance;
- does not infer that an evidence source applies to the patient;
- does not infer causality from local treatment outcomes;
- does not automatically learn from patient records;
- does not replace independent physician review.

`open_escalations` is deliberately scoped to findings from the latest safety
evaluation for that visit. The cross-visit escalation queue remains a separate
administrative workflow and may contain older escalations that are not included
in this per-visit field.

A missing safety finding, a matching context hash, or an empty escalation list
must never be interpreted as proof that care is safe or appropriate.


## Companion treatment-options roadmap

The clinical console may load a separate read-only endpoint,
`GET /api/v1/visits/{visit_id}/treatment-options-roadmap`, beside the copilot
snapshot. The roadmap is intentionally separate from the immutable copilot
manifest because it is an aggregate decision-support calculation over local
outcome history rather than part of the visit's stored evidence manifest.

When its safety and minimum-cohort gates are satisfied, it can show multiple
active-protocol options using a predefined similar-patient cohort and explicitly
descriptive local outcome statistics. Options are not ranked or selected.

See [Similar-Patient Treatment Options Roadmap](SIMILAR_PATIENT_TREATMENT_ROADMAP.md).
