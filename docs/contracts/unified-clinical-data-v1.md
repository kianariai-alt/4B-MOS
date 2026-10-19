# Unified Clinical Data Contract 1.0.0

Owner: Clinical Intelligence Integration. Status: experimental internal contract.
Implementation: `backend/app/schemas/clinical_integration.py`.
Machine-readable producer schema: `unified-clinical-core-output-1.0.0.schema.json`.

This document is the shared boundary for the independent orthopedic and imaging
workstreams. It does not define their medical reasoning, imaging pipelines or
model training. Existing 4B-MOS identifiers remain authoritative. These shapes
are **not FHIR resources, a FHIR server, profiles, or validated FHIR exchange**.

## Entities and existing identifiers

| Entity | Contract shape / authoritative 4B-MOS record | FHIR R4 design reference, not an implemented mapping |
| --- | --- | --- |
| Patient | `PatientReference.patient_id` → `patients.id`, internal envelope only | Patient |
| Clinical Visit | `VisitReference.visit_id` → `visits.id` | Encounter |
| Clinical Assessment | `ClinicalAssessmentReference` → final `clinical_intakes.id`, version, digest | ClinicalImpression |
| Clinical Finding | `CoreFinding` + `IntegratedFinding`, core=`orthopedic`; typed existing observation | Observation |
| Imaging Study | `ImagingStudyReference` → `paraclinical_reports.id`, version, digest; report proxy only | ImagingStudy / DiagnosticReport |
| Imaging Finding | `CoreFinding` + `IntegratedFinding`, core=`imaging`; report observation ID required | Observation linked to DiagnosticReport |
| Clinical Evidence | `ClinicalEvidenceReference` → existing immutable evidence brief ID and hashes | DocumentReference / clinical evidence artifact |
| Knowledge Reference | `KnowledgeReference` → approved Medical Knowledge Registry fact ID, key, version, digest and source IDs | Internal governed knowledge artifact; no one-to-one mapping claimed |
| Decision Support Result | `DecisionSupportResult`, persisted in an immutable `IntegrationRunSnapshot` | GuidanceResponse (conceptual only) |
| Physician Review | `PhysicianReview`, separately authored and hashed | Provenance agent/activity (conceptual only) |
| Source Approval | `PhysicianApproval`, authoritative source finalization attribution | Provenance agent/activity (conceptual only) |
| Model / Rule / Adapter Version | `ComponentVersion`, `Provenance` and safety rule-set digest | Provenance / Device concepts |
| Audit Event | `IntegrationAuditEvent` projection over existing `audit_logs` | AuditEvent |

An imaging report proxy does not prove DICOM Study/Series/SOP identity. This
version always sets `dicom_identity_verified=false`; local adapters set
`modality=unknown`. Do not infer MRI from report title or a report-key name.
Study/series binding, image quality and validated modality metadata require the
imaging workstream and a later reviewed contract revision.

## Producer envelope and provenance

Each `CoreOutput` requires:

- Exact `contract_version="1.0.0"`, `core`, existing `visit_id`, and the canonical
  `clinical_context_sha256` supplied by the integration service.
- A trusted `ComponentVersion`: component ID, version, artifact/configuration
  SHA-256 and kind (`adapter`, `model`, `rule`). The response must match the
  version advertised by its registered adapter. A model must use an actual
  governed checkpoint/configuration identity when a real model is connected.
  The initial passthrough adapters use a deterministic mapping-version digest;
  this is not a model weight hash or clinical validation.
- Timezone-aware generation and validity timestamps, bounded findings, unique
  finding IDs, and status `available`, `missing` or `unavailable`.
- For every finding: exact source record ID, version, content digest and field
  or observation ID; the existing typed `ParaclinicalObservationInput`; origin
  `record` or `model`. Only model-origin data may carry confidence in [0, 1].

No producer can set an approval field, clinical clearance, patient demographics,
or additional top-level keys. Foreign visit/context/component identities,
future or expired responses, unknown source references, changed record values,
cross-core source categories and duplicate source findings fail closed. Invalid
producer outputs remain traceable as core status/issues, not clinical findings.

The model source is an existing observation reference in this first version.
Raw DICOM-only candidates require the imaging workstream's draft report
normalization before they can enter this contract. No arbitrary inference API
accepts a client-supplied `approved=true` or trusts a remote reviewer ID.

## Typed values, terminology and conflicts

Reuse the existing observation contract: quantity with unit; string; boolean;
integer; coded value with coding system; timezone-aware datetime; or explicit
absence. Exactly the corresponding value field is allowed. Missing data is not
encoded as a negative finding. Existing `LOINC`, `SNOMED_CT`, `LOCAL`, `OTHER`
and UCUM-style unit fields are preserved. A terminology server, code correctness
and equivalence validation are not implemented.

The integration engine performs one narrow consistency check: different boolean,
coded or integer values across cores for the exact same code/system/version,
body-site string and value type. It flags these for review without choosing a
winner. It does not equate clinical and imaging findings with different codes,
parse free text, infer laterality, compare unmatched units, or perform medical
reconciliation. Numeric clinical thresholds belong to approved clinical rules.

## Review and trust

The output separates:

1. `raw_record_references`: links back to existing source documentation.
2. `cores`: producer outputs with component provenance and model origin.
3. `confirmed_findings`: exact values from current final records finalized by a
   physician resolved on the server; every item has source approval attribution.
4. `unreviewed_findings`: all model-origin values and records whose finalizer
   cannot be established as a physician. Confidence never substitutes for review.
5. `reviews`: immutable independent physician review events returned alongside
   the saved result. The original result remains unchanged.

`confirmed_source` means physician-finalized source documentation, not diagnostic
certainty, model validation or proof of source accuracy. The existing finalizer
role is resolved conservatively from the current user table; a later role change
can invalidate prior attribution. Historical role attestation is deferred.

The `approve_summary` action approves only this exact combined summary for
discussion. It never confirms individual model findings, selects treatment,
creates a prescription or grants procedural authorization. It is refused when
the run is blocked, stale or unverifiable. `defer`, `reject` and `request_revision`
remain available to document a physician's response to an incomplete snapshot.
New reviews are appended, not silently applied to source records or previous
reviews. Existing treatment decisions retain their separate guarded workflow.

## Knowledge and evidence

Selected knowledge IDs are resolved on the server through the existing Registry,
with content verification, independent review status and validity-date checks.
The result preserves grade, version, sources and validity without inferring
patient applicability. No patient record is promoted into general knowledge.

Existing evidence briefs are represented as historical immutable references;
`context_matches` is distinct from knowledge currency. Their embedded historical
facts are not silently treated as currently approved facts. Current knowledge is
represented only in the separately resolved `knowledge` array. Sources and
knowledge references remain retrievable through the existing Registry API.

## Persistence and invalidation

Snapshots bind the result to the engine version, clinical-context digest,
Copilot manifest digest (including safety, evidence and outcomes), active safety
rule-set digest, component versions and core-output digests. The stored
`result_sha256` hashes the entire run snapshot, including run ID, request digest,
actor and creation time. It is a reproducibility/corruption check, not a digital
signature or trusted timestamp.

On every read and physician approval attempt, verify stored content and compare
live dependencies. Changed/retired/expired knowledge, changed source records,
source-review attribution, Copilot manifests, safety rules, model/adapter or
engine versions, visit status/patient association and expired validity windows
make a result stale or unverifiable. The saved artifact is retained unchanged.

The administrative review window is at most 24 hours and may be shortened by a
producer. This is **not a validated clinical maximum age for an imaging study**.
Registry checks use the UTC evaluation date; mismatch with a separately generated
safety evaluation conservatively blocks review. A later cross-service clinical
date policy must be coordinated with the safety workstream.

Idempotency is scoped to `(visit_id, request_key)`, with actor and exact request
inputs in the fingerprint. Same request returns the saved artifact, including
its current freshness. Reusing a key for different inputs/actor is a conflict.
A new key creates a fresh run; retry never rewrites the earlier artifact. Review
keys are scoped to the run and check exact action, rationale, hash and physician.

## Privacy and access

The internal result contains only the existing patient ID, once at the envelope
level. `CoreInput` excludes patient ID, demographics, history, allergies, URLs,
tokens and source-performer names. Each core receives only its relevant typed
observations. Examination narratives can still contain identifying text; this
is data minimization, not a claim of de-identification. The default adapters
are local only; connecting any external processor requires a separately reviewed
redaction/pseudonymization and authorization boundary.

Read/create: active admin or physician. Review: active physician only. These
reuse current clinic-wide RBAC; patient-specific authorization is not introduced.
Audit metadata contains IDs, hashes, actions and counts, without observations,
demographics, exception messages or physician rationale. New endpoints use
`Cache-Control: no-store`. Access/audit retention and database privileges remain
the deployment's responsibility.

## Version compatibility and coordination

- Version 1.0.0 is an exact-match producer contract. Unknown fields/versions are
  rejected; additive fields also require coordination while consumers are strict.
- Consumers preserve existing source IDs, observation typing and content hashes;
  no new patient identifier authority is created.
- A proposed change documents producer/consumer impact here and supplies contract
  fixtures/tests for both core branches. Introduce an explicit adapter for a new
  version; do not reinterpret saved 1.0.0 snapshots in place.
- DICOM lineage, model-specific physician review, calibrated probabilities,
  cross-code reconciliation and terminology equivalence are future versions.

Official references reviewed for this design:
[Observation](https://hl7.org/fhir/R4/observation.html),
[DiagnosticReport](https://hl7.org/fhir/R4/diagnosticreport.html),
[ImagingStudy](https://hl7.org/fhir/R4/imagingstudy.html),
[ClinicalImpression](https://hl7.org/fhir/R4/clinicalimpression.html),
[GuidanceResponse](https://hl7.org/fhir/R4/guidanceresponse.html),
[Provenance](https://hl7.org/fhir/R4/provenance.html),
[AuditEvent](https://hl7.org/fhir/R4/auditevent.html).
