# Controlled-Pilot Readiness

Stage 25 adds a read-only operational gate for deciding whether the 4B-MOS
environment has passed the prerequisites that the software can actually verify.

It does not authorize clinical use.

## Surfaces

Admin API:

`GET /api/v1/pilot-readiness`

Deployment command:

```sh
python -m backend.tools.pilot_readiness
python -m backend.tools.pilot_readiness --format json
```

A zero CLI exit status means only that the automated prerequisites passed.

## Automated checks

The gate returns fixed pass/fail/blocked codes and no patient values, usernames,
protocol content or clinical text.

### Production runtime

Requires:

- `ENVIRONMENT=production`;
- debug disabled;
- public bootstrap disabled.

### Current database schema

Uses the same shared database-readiness definition as `/health/ready` and the
release preflight.

Stage 25 expands that shared definition through the current Decision, Outcome,
Governance, Release and Recovery tables so a database missing a later clinical
workflow table cannot appear ready merely because older tables exist.

### PostgreSQL deployment engine

Controlled pilot readiness requires PostgreSQL.

SQLite remains supported for local/development workflows and disposable tests,
but its serialized database-writer behavior is not accepted as the concurrency
basis for the controlled clinical pilot gate.

### Staff role separation

The automated gate verifies, without returning identities or counts, that active
accounts exist for at least:

- one administrator;
- two physicians;
- one nurse;
- one operator.

Two physicians are required because independent clinical governance review
cannot be performed by the case author.

### Protocol registry and lineage

The gate requires at least one active protocol and verifies protocol lineage
through the governed release/recovery service.

A conflicting lineage or multiple active versions for one protocol code blocks
the gate.

This verifies registry integrity only. It does not certify that a protocol is
clinically appropriate.

### Clinical safety registry

At least one currently active safety rule must exist and its approved
knowledge-linked snapshot must pass the existing integrity checks.

The gate does not judge whether the rule set is clinically comprehensive.

### Decision/Treatment/Outcome provenance

The Clinical Learning Review is executed read-only so any existing immutable
Decision, Treatment and Outcome provenance must pass its integrity checks.

No aggregate or patient-level values from that review are returned by the pilot
readiness response.

### Protocol governance history

Every governance case, release and recovery record is re-read through the
existing immutable integrity validators.

Broken governance evidence blocks the automated gate.

## Manual gates

The following remain `manual_required` and are never auto-passed by 4B-MOS:

- clinical sign-off of protocol content;
- clinical sign-off of safety-rule content;
- backup/restore rehearsal;
- network/perimeter security review;
- monitoring and alert-delivery validation;
- human clinician/staff UI acceptance;
- privacy, retention and legal review.

A future workflow may preserve evidence that these reviews occurred, but Stage
25 intentionally does not convert absence of machine evidence into an automatic
approval.

## Output semantics

The strongest automated status is:

`automated_prerequisites_passed`

Even then the response retains:

- `controlled_pilot_authorized = false`
- `is_clinical_clearance = false`
- `requires_human_release_decision = true`

The gate therefore cannot be used as a treatment authorization, clinical
clearance or production release signature.

## Relationship to existing readiness checks

- `/api/v1/health` is liveness.
- `/api/v1/health/ready` verifies database schema readiness.
- `python -m backend.tools.release_preflight` verifies redacted deployment
  prerequisites.
- Stage 25 adds broader controlled-pilot automated prerequisites and the explicit
  list of manual acceptance gates.

A pass at one layer does not imply a pass at the next layer.
