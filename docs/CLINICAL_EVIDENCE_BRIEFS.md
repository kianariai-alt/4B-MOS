# Clinician-selected clinical evidence briefs

Stage 18 lets an active physician preserve a source-linked evidence summary for
one exact, current clinical-context snapshot. The physician selects every
approved knowledge fact. The system preserves and verifies that selection; it
does not infer which fact applies, rank treatments, or issue a recommendation.

## Safety boundary

- A brief requires a current `final` clinical intake and an exact optimistic
  `clinical_context_sha256`. A changed intake or report produces a conflict.
- Every selected fact must be `approved`, inside its validity window, and match
  the exact content hash last read by the physician.
- Facts are ordered by `fact_key` and version only for deterministic storage.
  This order is not relevance, priority, strength, or treatment ranking.
- The immutable snapshot includes the physician's question, context record IDs
  and hashes, complete selected fact/source snapshots, knowledge date, actor
  snapshot, known limitations, and canonical SHA-256 values.
- Every response explicitly states that it is not a recommendation, treatment
  ranking, risk score, clinical clearance, or time-critical output and that
  independent physician review is required.
- There is no diagnosis, treatment directive, dosage, prognosis, follow-up
  directive, automatic literature retrieval, automatic fact matching, outcome
  learning, or patient-to-knowledge promotion.
- Audit events keep identifiers, counts, hashes, method, output type and safety
  flags. They do not duplicate the physician's question, patient values, or
  evidence statements.
- SHA-256 detects one-sided changes. It is not a digital signature, trusted
  timestamp, regulatory determination, or defense against privileged SQL that
  replaces both content and hashes.

This deliberately narrow design follows the transparency direction in the
[FDA Clinical Decision Support Software FAQ](https://www.fda.gov/medical-devices/digital-health-center-excellence/clinical-decision-support-software),
the FDA's [Digital Health Policy Navigator](https://www.fda.gov/medical-devices/digital-health-center-excellence/digital-health-policy-navigator),
the ONC [HTI-1 decision-support intervention transparency materials](https://www.healthit.gov/topic/laws-regulation-and-policy/health-data-technology-and-interoperability-certification-program),
and the traceable evidence concepts in
[HL7 FHIR Clinical Reasoning](https://hl7.org/fhir/R5/clinicalreasoning-module.html).
Those references informed engineering safeguards; they do not certify this
software or decide its regulatory status.

## Roles and API

Only an active physician may create a brief. Admins, physicians and nurses may
read briefs and their minimized audit history.

| Method and path | Purpose |
| --- | --- |
| `POST /api/v1/visits/{visit_id}/evidence-briefs` | Record one physician-selected immutable evidence snapshot |
| `GET /api/v1/visits/{visit_id}/evidence-briefs` | List and integrity-check the visit's briefs |
| `GET /api/v1/evidence-briefs/{brief_id}` | Read and integrity-check one snapshot |
| `GET /api/v1/evidence-briefs/{brief_id}/audit-logs` | Read its minimized creation audit history |

The create request contains a clinical question, the exact current-context hash,
and one through twenty fact IDs with their expected hashes. There are no update
or delete endpoints. If context or evidence changes, the physician must review
the new state and create another brief.

## Integrity and concurrency

Creation shares the visit-level clinical-record write lock used by intake,
reports, safety evaluations and finding reviews. PostgreSQL CI proves a
competing same-visit writer receives the bounded lock conflict. Database foreign
keys restrict deletion of the visit, intake and actor. Governed APIs expose no
fact/report deletion path; a missing JSON-referenced fact or report makes the
brief fail its integrity check.

Historical reads validate the stored payload hash, record columns, current
contents of the referenced immutable clinical records, exact selected fact
versions, source snapshots and knowledge-set hash. A later retirement or
supersession of a fact does not erase an already-created brief.

## Controlled deployment

1. Obtain clinical-governance approval for intended use, source eligibility,
   evidence review cadence, conflicts, expiry, wording and responsibility.
2. Drain older workers, take a verified backup, and rehearse the upgrade on a
   disposable restored copy. The migration and expected head are
   `e6b7c8d9a401`.
3. Confirm the new `clinical_evidence_briefs` table is empty, run the read-only
   preflight, and deploy only the matching application/database pair.
4. In staging, verify physician-only creation, stale context/fact conflicts,
   retired-fact historical reads, tamper detection, audit minimization and
   same-visit concurrency using synthetic records.
5. Validate the clinician UI, terminology service, intended PostgreSQL topology,
   monitoring, access controls and human-factors workflow separately before use.

Downgrade is refused while any brief exists and offline downgrade is refused.
Never delete clinical evidence history to force older code onto the database;
restore the reviewed application/database pair through the governed recovery
process.

## Explicitly deferred

- automatic patient-to-evidence matching or applicability inference;
- diagnostic, therapeutic, dosage, prognostic or follow-up recommendations;
- treatment ranking, risk scoring, time-critical alerts or clinical clearance;
- terminology validation, unit conversion and FHIR import/export;
- automated source surveillance, ingestion or knowledge approval;
- outcome aggregation, bias monitoring, model training or autonomous learning;
- external signatures/timestamps and regulatory or medical-device validation.
