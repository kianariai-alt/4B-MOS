# Patient portal and shared-care foundation

Status: a feature-gated single-installation pilot is implemented. It includes
temporary patient sessions, encrypted submissions/images/messages, staff grants,
audited review, and identity-checked conversion into reception and a visit. It is
disabled by default. There is no verified patient account, OTP provider, SaaS tenant
isolation, autonomous clinical assessment or cross-clinic authorization. Optional
region-to-physician mappings attach a snapshot of an approved bank at submission;
the patient answers bounded conditional questions with unknown/decline choices.
Bank retirement or replacement stops new answers to that snapshot.

## Product flow

Clinic website / QR → branded portal → verified patient session → patient-authored
request → admission receipt → staff review → linked patient and visit → physician
reviewed clinical intake. Remote requests are not booked appointments or a promise
of remote treatment. Admission receipts are not credentials.

First release: Persian mobile-first arrival/remote form, staff queue, rewritten
JPEG/PNG uploads, clinician-authored follow-up questions and a source-labelled
summary of patient statements and approved-bank conditional question branching.
Later releases: PDF/DICOM, verified patient accounts and a shared-care workspace.
A request must be durable before issuing a receipt.
Repeat submission with the same tenant/session/request key returns the same receipt;
reuse with different content must conflict. No duplicate visits on retry.

## Clinic boundaries before public launch

Introduce Clinic, verified ClinicDomain, clinic memberships and explicit tenant
ownership throughout patients, visits, records, files and jobs before exposing a
multi-clinic service. The current schema is not tenant isolated. Do not claim SaaS
isolation until database and endpoint tests prove it. Existing installations migrate
to one default clinic with reconciliation and backup, not implicit shared access.

Resolve clinic from an allowlisted, verified domain or server-side portal mapping;
do not trust a posted clinic_id or arbitrary Host/X-Forwarded-Host. QR codes carry
public clinic destinations only, no patient identifiers or bearer credentials.
The clinic website links to an HTTPS portal; medical data does not enter WordPress,
advertising pixels, analytics events, URL parameters or ordinary website forms.

Patient identity uses a separate authenticated session and verified contact channel;
staff credentials and roles are never reused for public access. Phone ownership is
not proof of clinical identity: staff resolve possible duplicate records. Support
international numbers and alternate verified identity paths in later releases.
Apply expiry, throttling, abuse controls, secure HttpOnly cookies, CSRF protection,
private responses and object-level authorization before launch.

## Patient statements and consent

The new PatientRequestCreate contract accepts patient statements only. Server-side
context supplies tenant and patient identity; the server generates receipt, time,
provenance and status. Reject posted diagnosis approvals, assigned physician,
verification flags or finalized clinical records. Empty allergy/medication lists
mean not supplied, not confirmed absent. Keep reported, proposed, prescribed and
actually administered medication records distinct.

Persist notice version and consent evidence with authenticated identity and server
time. Marketing is independently optional and defaults off; refusal never changes
care priority. Audio, education, research and cross-clinic sharing have separate
purposes. Patients may withdraw future access; retain prior lawful audit evidence
under an established retention policy. Patient care does not depend on points,
advertising consent or participation in training data collection.

## Documents and assistant review

Private object storage with tenant/request ownership, strict size and format limits,
malware scanning and quarantine before extraction. Avoid active HTML/SVG content.
Authorize every download; use short-lived access and audit access. Uploaded text
is untrusted evidence, never executable instructions for the assistant.

Question sequences use versioned physician-approved banks, bounded branching and
explicit unknown answers. Safety notices use reviewed rules; absence of an alert
does not mean safety. Urgent guidance takes precedence over service promotion.
Display extraction uncertainty and require review before clinical finalization.
No autonomous diagnosis, dosing or cross-specialty contraindication claims based
on this input contract. Promotional content is identified and separate from
clinical recommendations; no guaranteed outcomes.

## Shared care, not globally open records

A future CareTeamGrant binds patient, source clinic, recipient clinician and clinic,
purpose, record categories, effective/expiry times and withdrawal. A grant is only
one authorization condition: active identities, memberships, patient linkage and
record ownership must also pass. Cross-clinic sharing is denied by default.
Do not merge identities by name/phone or silently copy entire records between tenants.

Each shared observation retains author, specialty, source clinic, event time,
verification status and version. Corrections append provenance; another specialty
cannot overwrite the source physician. Medication reconciliation tracks reported
use separately from prescribing and discontinuation events. Shared-care summaries
show source and freshness, unresolved discrepancies and unanswered consultations.
Renal context may be relevant to orthopedic prescribing, but alerts require current
validated rules, units, lab timestamps and physician review; no fabricated thresholds.
Revocation blocks future reads, including file URLs, caches and pending summaries.

## Release checks

Before enabling endpoints: tenant migration and negative isolation tests; patient
session and object-access tests; idempotency and concurrent submission tests;
separate consent audit; no patient-data leakage through logs/URLs/analytics; secure
upload tests; staff review and explicit conversion into existing reception flow;
mobile accessibility/RTL testing; backups and restore exercise; public HTTPS hosting
and clinic domain setup. A localhost QR cannot serve patients outside the PC.

Only then enable one-clinic pilot. Multi-clinic SaaS and shared-care access remain
separate gated releases, with tested grant expiry, withdrawal and recipient access.
