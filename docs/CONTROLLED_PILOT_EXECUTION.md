# Controlled pilot execution and post-pilot evidence

Stage 29 binds each pilot visit to the exact independent human release decision,
clinician-selected versioned protocol and current clinician decision. Stage 30
provides a read-only post-pilot evidence manifest for human acceptance review.

## Clinical boundary

These features do not prescribe a treatment, verify the actual authenticity
of a patient consent document or replace the treating physician's decision.
A consent-document reference and physician attestation are recorded but the
document itself must be verified through the clinic's approved procedure.

## Environment gate

Set `PILOT_ENFORCEMENT_ENABLED=true` only in an isolated controlled-pilot
deployment with approved PostgreSQL and complete manual release gates. The
default is false. Production pilot enrollment is rejected while this flag is
false. Turning the flag on in a shared general clinic installation blocks
new Treatment creation for ALL visits not enrolled in that pilot. Do not enable
it on a routine clinic instance without an approved separation/migration plan.

The same service also enforces scope whenever a visit has already been enrolled,
even if the deployment flag is subsequently off. Revoking the flag is NOT a
supported emergency-stop mechanism. Use the append-only stop endpoint.

## Enrollment

`POST /api/v1/pilot-execution/releases/{release_id}/visits/{visit_id}/enroll`

Only the physician who authored the CURRENT exact clinician decision for that
visit may enroll it. The request supplies the release SHA-256, protocol ID,
clinician-decision ID/hash, consent-document reference, actual confirmed-at
timestamp and explicit physician statement.

The service rejects stale/held/expired/stopped releases, non-active or
out-of-scope protocols, an unrelated/superseded clinician decision, a visit
already containing a Treatment, duplicate enrollment, a changed launch package
and a reached enrollment cap. Enrollments and audit records commit together.
The release row is locked in PostgreSQL to serialize concurrent enrollment and
stop commands; the pilot release gate already requires PostgreSQL.

Enrollment is immutable and one per visit. It is NOT treatment authorization.

## Runtime enforcement

A controlled-pilot visit is rechecked on new Treatment creation, creation of a
session, transition into `in_treatment`, and entry of a new administration
component. The check binds the exact active protocol, versioned clinician
decision, enrollment/release checksum, time window, stop state and current
launch-package prerequisites. A new or superseding decision requires a new
governance process; no silent relink is supported.

The standard Treatment creation path also refuses non-enrolled visits when the
dedicated pilot-enforcement flag is on. Existing routine clinical care should be
deployed separately from this mode.

## Immediate stop

`POST /api/v1/pilot-execution/releases/{release_id}/stop`

Active admins or physicians can record an append-only global stop, with a
reason category, rationale, actor and SHA-256. Exactly one stop record exists
per release. A stopped release cannot be restarted by editing the stop or
decision; a new independently governed release is required.

Stop blocks NEW pilot starts and administrations. It does not cancel essential
clinical care, and previously started sessions may still need completion,
discharge, adverse-event documentation or escalation. The clinic must preserve
an emergency clinical-care and late-documentation procedure outside the pilot
intervention workflow. Never rely on the software stop alone for physical or
patient-safety escalation.

## Human post-pilot acceptance

`GET /api/v1/pilot-execution/releases/{release_id}/acceptance`

Returns an anonymized operational/evidence summary: enrollments, visits with
Treatment, visits with Outcome, observed follow-up entries, adverse-event
entries reported within Outcome records, immutable enrollment/outcome hashes,
the stop hash and a manifest SHA-256. It deliberately does NOT calculate
treatment effectiveness, impute missing data, certify adverse-event
surveillance or authorize expansion. Even `ready_for_human_review` means only
that each enrolled visit has at least one recorded Treatment and Outcome.

Follow-up maturity, adverse-event review, protocol applicability, consent and
independent clinical acceptance remain human responsibilities. The report is
read-only; its manifest is reproducible for unchanged source evidence but is
not a digital signature.

## Console

The Persian "اجرای پایلوت" workspace is visible to admin and physician roles.
A physician may enroll only after entering the exact clinician-decision and
consent references. Admins and physicians can record a confirmed global stop
and inspect the operational acceptance manifest. No patient identifiers are
stored in browser local storage.
