# Protocol Learning & Governance Workspace

Stage 22 turns the read-only Clinical Learning Review into a governed protocol
review workflow without allowing the software to change clinical protocols on
its own.

## Governance signals

`GET /api/v1/learning/governance/signals`

Signals describe data maturity and data-quality gaps for each exact protocol
code/version. Examples include:

- insufficient or limited outcome volume;
- missing Decision-linked Treatments;
- incomplete patient/physician ratings;
- incomplete pain or function scores;
- missing early, intermediate or long-term follow-up;
- eligibility for human pattern review when data volume is larger and the
  tracked quality flags are absent.

Signals are descriptive. They are not protocol-change recommendations and do
not rank treatment performance.

## Governance cases

A physician can open an immutable case with:

`POST /api/v1/protocol-governance/cases`

Supported case types are:

- `collect_more_data`
- `monitor_no_change`
- `revision_candidate`
- `deactivation_candidate`

Every case freezes:

- the exact Clinical Learning Review SHA-256;
- the exact protocol snapshot;
- the per-protocol learning-review snapshot;
- the physician's rationale;
- requested additional evidence/data;
- any proposed protocol revision payload;
- author and timestamp.

A revision candidate must preserve the protocol code and treatment type, use a
new version, and cannot target a version that already exists.

Opening a case never creates, edits or deactivates a protocol.

## Independent review

Review events are append-only:

`POST /api/v1/protocol-governance/cases/{case_id}/reviews`

Clinical review actions:

- `clinical_approve`
- `clinical_reject`
- `request_changes`

Only a physician can perform clinical review, and the case author cannot perform
their own independent clinical review.

Operational review actions:

- `operational_acknowledge`
- `operational_hold`

Only an administrator can perform operational review, and operational review
requires a current clinical approval.

## Status model

Cases move through derived states without rewriting prior records:

- awaiting clinical review;
- changes requested;
- clinically rejected;
- awaiting operational review;
- operational hold;
- approved for manual action.

Even `approved_for_manual_action` does not modify the protocol registry. A
separate explicit manual protocol action is still required.

## Clinical boundary

This workflow intentionally separates:

1. local observational data,
2. data-quality signals,
3. human governance deliberation,
4. actual protocol version management.

The system does not infer a protocol parameter change, does not automatically
promote or demote a protocol, and does not treat local observations as causal
evidence.
