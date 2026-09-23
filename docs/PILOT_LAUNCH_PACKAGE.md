# Pilot Launch Package

Stage 27 freezes the complete controlled-pilot evidence manifest after all
automated prerequisites and all seven independently reviewed manual gates align.

The package is release evidence. It is not a launch authorization or clinical
clearance.

## Packageability

The preview is available at:

`GET /api/v1/pilot-readiness/manual-gates/launch-package-preview`

A preview is `packageable` only when:

1. automated controlled-pilot prerequisites are currently passing;
2. each of the seven manual gates has a latest approved attestation;
3. every latest attestation is bound to the current readiness SHA-256;
4. every attestation has an immutable approve review;
5. all seven attestations use one identical `release_ref`;
6. no launch package already exists for that release reference.

Any mismatch produces a fixed issue code and blocks freezing.

## Manifest

The package manifest stores, for each gate:

- gate name;
- attestation generation;
- attestation ID and SHA-256;
- review ID and SHA-256.

It does not duplicate the free-text attestation statement, review rationale or
evidence reference.

## Freeze

Only an active administrator can freeze a package:

`POST /api/v1/pilot-readiness/manual-gates/launch-packages`

The request must echo:

- the current readiness SHA-256;
- the exact release reference;
- all seven expected gate names and attestation SHA-256 values.

The service rebuilds the preview immediately before the write and refuses stale
or incomplete evidence.

## History

Frozen packages are immutable and readable by administrators and physicians:

`GET /api/v1/pilot-readiness/manual-gates/launch-packages`

`GET /api/v1/pilot-readiness/manual-gates/launch-packages/{package_id}`

One release reference can have at most one package.

## Safety boundary

Every package explicitly preserves:

- `controlled_pilot_authorized = false`
- `is_clinical_clearance = false`
- `requires_human_release_decision = true`

The next stage records the human release decision against this exact immutable
package rather than against live, drifting state.
