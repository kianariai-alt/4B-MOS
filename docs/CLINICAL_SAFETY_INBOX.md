# Clinical safety inbox

Stage 20 exposes the existing deterministic safety-rule evaluations and
append-only finding-review timelines in the same-origin staff console at
`/app/`. It adds a read-only aggregate API for the browser and role-gated
controls for actions already enforced by the backend.

This stage adds no migration, rule content, diagnosis, treatment recommendation,
clinical-clearance decision, notification service or automatic learning.

## Safety boundary

- The inbox displays only stored results from approved, deterministic rules. It
  does not infer a diagnosis, rank treatments, generate a care plan or decide
  whether treatment may start or continue.
- `no_alerts` means no configured active rule matched the available final data.
  `no_active_rules` means no rule was evaluated. Neither is evidence that risk is
  absent, and every aggregate response states `is_clinical_clearance: false`.
- The server compares the latest evaluation's clinical-context hash with the
  current final context. A mismatch is displayed as stale; the old snapshot and
  its review history remain intact.
- A review event documents that a clinician acknowledged, escalated or assessed
  one immutable finding snapshot. It never changes, hides, dismisses or
  overrides the finding or its evaluation result.
- Patient records, review dispositions and outcomes never promote themselves to
  rules or general medical knowledge.
- Display order follows the immutable evaluation snapshot. It is not risk,
  urgency or treatment ranking.

## Staff journey

1. Sign in to `/app/` with an active authorized account.
2. Open **صندوق ایمنی بالینی**. Stage 21 first exposes the minimal verified
   cross-visit escalation queue; selecting an item opens its exact visit without
   exposing review notes in the aggregate list.
3. Alternatively, open a visit from a live-flow card or enter an exact visit ID.
4. Review the current-context hash and the latest verified evaluation snapshot.
   If the context changed, the console marks the snapshot stale.
5. An admin or physician may confirm and run a new evaluation against the exact
   current-context hash. A conflict requires reloading rather than evaluating
   unexpected input.
6. Review each finding, governed-rule metadata, evidence identifiers and the
   condition trace. The trace contains condition metadata and matched record IDs,
   not duplicated patient values.
7. A physician or nurse may append an acknowledgment or escalation. Escalation
   requires a note. Only a physician may append the terminal assessment with an
   allowlisted disposition, reason and note.
8. Confirm the immutable event. The browser submits the exact evaluation-result
   hash, reloads the verified aggregate and exposes no edit or delete control.

## Roles

| Capability | admin | physician | nurse | operator | viewer |
| --- | --- | --- | --- | --- | --- |
| Read inbox and timelines | yes | yes | yes | no | no |
| Run a new deterministic evaluation | yes | yes | no | no | no |
| Record acknowledgment or escalation | no | yes | yes | no | no |
| Record terminal assessment | no | yes | no | no | no |
| Read cross-visit open-escalation queue | yes | yes | yes | no | no |

The browser hides unavailable actions for usability. API authorization remains
the security boundary and independently enforces every row in this table.

## Aggregate API

All paths are below `/api/v1` and require authentication.

`GET /visits/{visit_id}/safety-inbox` is available to admins, physicians and
nurses. It returns:

- the server-computed current clinical-context hash;
- the latest integrity-checked evaluation, or `null` if none exists;
- `evaluation_matches_current_context`, which is `true`, `false`, or `null`
  when no evaluation exists;
- each finding paired with its complete integrity-checked review timeline; and
- `is_clinical_clearance: false`.

The aggregate endpoint performs no writes. Evaluation and review writes continue
to use the existing endpoints and optimistic hashes documented in
`CLINICAL_SAFETY_RULE_ENGINE.md` and
`CLINICAL_SAFETY_REVIEW_WORKFLOW.md`.

`GET /safety/escalations` exposes only minimal routing metadata for verified open
escalations. It omits review notes and condition traces, preserves stale-context
visibility and explicitly states that its oldest-first order is not clinical
priority. See `CLINICAL_SAFETY_ESCALATION_QUEUE.md`.

## Browser and concurrency controls

- Access tokens remain in JavaScript memory only; logout, reload or closing the
  page discards them.
- All returned strings are inserted with `textContent`; no clinical/API value is
  interpreted as markup.
- Late responses from a prior login are ignored with a session-generation guard.
- Evaluation and review writes require explicit confirmation and the server hash
  last read by the browser. `409` responses instruct the user to reload.
- The console stores no offline patient data, has no service worker, opens no
  external source URL and sends no browser notification.
- Backend append-only constraints, integrity verification, role checks and the
  visit-level write lock remain authoritative.

## Controlled acceptance

Before staff use, validate with synthetic staging records:

1. admin/physician/nurse read access and operator/viewer denial;
2. admin/physician evaluation and nurse denial;
3. nurse acknowledgment/escalation and physician-only assessment;
4. stale-context warning after a finalized intake/report correction;
5. stale evaluation/review-hash conflict handling;
6. terminal assessment, absence of edit/delete/dismiss/override controls and
   persistence across reload;
7. Persian terminology, keyboard navigation, small-screen layout, accessibility
   and supported browsers; and
8. downtime, staffing, escalation response and independent clinical judgment.

A green test or rendered UI is an engineering gate only. It is not clinician
acceptance, clinical validation, regulatory approval or production authorization.

## Explicitly deferred

- external messaging, delivery deadlines and escalation-service monitoring;
- alert-fatigue policy, clinical prioritization and override authority;
- terminology-service validation, unit conversion and external FHIR exchange;
- diagnosis, treatment selection, recommendation or autonomous clearance;
- publication ingestion, patient-outcome learning or automatic rule updates;
- digital signatures, trusted timestamps and medical-device validation.
