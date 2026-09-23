# Human Pilot Release Decision

Stage 28 records the human release decision against one exact immutable Pilot
Launch Package.

A launch package remains evidence only. The release decision is a separate,
append-only event.

## Endpoint

Create a decision:

`POST /api/v1/pilot-readiness/manual-gates/launch-packages/{package_id}/release-decisions`

Read history:

`GET /api/v1/pilot-readiness/manual-gates/release-decisions`

`GET /api/v1/pilot-readiness/manual-gates/release-decisions/{decision_id}`

`GET /api/v1/pilot-readiness/manual-gates/launch-packages/{package_id}/release-decision`

## Independence

Only an active administrator can record the decision.

The administrator who froze the launch package cannot make the release decision
for that same package.

## Decisions

Two actions are supported:

- `authorize`
- `hold`

An authorize decision must freeze:

- package ID and SHA-256;
- start and expiry timestamps;
- maximum enrolled visits, from 1 through 100;
- one or more currently active protocol codes;
- human rationale;
- administrator identity and timestamp.

A hold decision carries no active pilot scope.

## Revalidation

Immediately before recording the decision the service verifies:

- the exact launch-package SHA-256;
- current automated readiness is still passing;
- the readiness SHA-256 still equals the package snapshot;
- every manual gate still points to the exact approved attestation frozen in the
  package;
- every protocol code in an authorize scope is currently active.

Any drift blocks the release decision.

## Safety boundary

An authorize decision means the organization has authorized a bounded controlled
pilot program.

It does not authorize treatment for an individual patient.

Every response preserves:

- `authorizes_individual_treatment = false`;
- `is_clinical_clearance = false`;
- `individual_clinician_decision_required = true`.

Stage 29 binds individual visits to this exact release decision and enforces the
bounded pilot scope.
