# Pilot Manual Gate Attestations

Stage 26 turns each Stage 25 manual gate into governed, immutable release
evidence. The workflow records human assertions; it does not decide that the
assertion is clinically or operationally true.

## Gates and roles

Clinical gates require an active physician author and a different active
physician reviewer:

- `clinical_protocol_signoff`
- `clinical_safety_signoff`

Operational gates require an active administrator author and a different active
administrator reviewer:

- `backup_restore`
- `security_perimeter`
- `monitoring_alerting`
- `human_ui_acceptance`
- `privacy_retention_legal`

For that reason the controlled-pilot automated role-separation prerequisite now
requires at least two active administrators and two active physicians, plus an
active nurse and operator.

## Snapshot binding

Every attestation includes the exact Stage 25 `readiness_sha256`.

Creation fails when:

- automated prerequisites are not currently passing;
- the submitted readiness hash is stale;
- the actor has the wrong role;
- a prior generation is still awaiting review;
- a supersession does not identify the current latest generation and SHA-256.

The readiness digest excludes its generation timestamp and is stable while the
verified readiness state is unchanged.

## Append-only generations

A gate starts at generation 1.

A later attestation never edits generation 1. It creates generation 2 and must
name the exact prior attestation ID and SHA-256. The database enforces one
generation number per gate and one direct successor per attestation.

## Independent review

Each attestation can have exactly one immutable review:

- `approve`
- `reject`

The author cannot review their own attestation. Review also rechecks that the
same readiness snapshot is still current and passing.

A rejected attestation remains part of history. Correction requires another
generation.

## API

Read status:

`GET /api/v1/pilot-readiness/manual-gates`

Read history:

`GET /api/v1/pilot-readiness/manual-gates/attestations`

Create attestation:

`POST /api/v1/pilot-readiness/manual-gates/attestations`

Review:

`POST /api/v1/pilot-readiness/manual-gates/attestations/{attestation_id}/review`

The Persian console exposes the same role-constrained workflow from the
controlled-pilot workspace.

## Integrity and privacy boundary

Attestation and review payloads have deterministic SHA-256 integrity digests and
ORM update/delete guards. Audit events contain the gate name, generation and
hashes, not the free-text statement or review rationale.

SHA-256 remains an integrity mechanism, not a digital or legal signature.
Privileged database access can still replace both content and hashes.

No attestation or approval sets clinical clearance or pilot authorization.
