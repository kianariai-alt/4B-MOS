# Clinical operations, evidence-review and safety-inbox console

The mobile-friendly staff interface is served from `/app/` by the same FastAPI
process as the API. It provides authenticated access to the existing clinic
live-flow projection, executes only workflow transitions returned by the backend
and exposes deliberately narrow evidence-review and clinical-safety workspaces
for authorized clinicians.

Stages 19–21 add no clinical policy, database migration, patient-data store,
offline mode or public patient portal. The API remains the authorization,
integrity and validation boundary.

## Operational journey

1. Open `/app/` over the approved HTTPS endpoint.
2. Sign in with an active staff account.
3. Review scheduled, checked-in, ready, in-treatment and
   awaiting-discharge columns.
4. Review wait-time and priority alerts calculated by the backend.
5. Confirm one of the actions explicitly allowed for that session.
6. The console sends the transition to the existing workflow endpoint and then
   reloads the authoritative live-flow state.
7. Use **خروج امن** before leaving the workstation.

Administrators, physicians, nurses and operators may use live flow according to
the existing API policy. Viewer accounts receive a role-denied message. A
completion action can still return `409` when clinical completion requirements
are not satisfied; the console does not bypass that guard.

## Physician evidence journey

Admins, physicians and nurses can open **مرور شواهد پزشک** from the tab or from
an active visit card. Admin and nurse access is read-only. Only an active
physician can create a brief.

1. Select an active visit or enter its exact visit ID.
2. The console reads the current final intake, final paraclinical reports and the
   canonical `clinical_context_sha256` calculated by the server.
3. Review the patient context. A brief cannot be created without a current final
   intake.
4. Search the approved-current knowledge registry. Search is initiated by the
   clinician; the console performs no patient-to-fact matching.
5. Manually select one through twenty facts. Nothing is preselected. Fact-key
   ordering is deterministic display order, not relevance or treatment ranking.
6. Enter the physician's clinical question and explicitly acknowledge the
   immutable, non-recommendation boundary.
7. Confirm creation. The console submits the exact context and fact hashes; a
   `409` forces a reload instead of recording stale context or evidence.
8. Read the immutable brief, selected source snapshots, limitations and hashes
   in the visit history. There is no edit or delete control.

The workspace does not diagnose, prescribe, calculate risk, rank therapies,
infer applicability, issue clearance or time-critical advice, retrieve external
literature, or learn from patient records. The physician remains responsible for
source applicability and independent clinical judgment.

## Clinical safety inbox journey

Admins, physicians and nurses can open **صندوق ایمنی بالینی** from the tab or
from an active visit card. The console loads the latest integrity-checked
evaluation together with every integrity-checked finding-review timeline.

1. Review the minimal cross-visit open-escalation queue or select an active visit
   / enter its exact visit ID. Queue rows omit notes and patient values.
2. Open an escalation to read its exact visit-level verified timeline.
3. Compare the latest evaluation snapshot with the server-computed hash of the
   current final clinical context. A mismatch is shown as stale.
4. Review rule metadata, source-fact identifiers and condition traces. Patient
   values are not duplicated into the trace.
5. An admin or physician may explicitly confirm a new deterministic evaluation.
6. A physician or nurse may append acknowledgment or escalation; only a
   physician may append a terminal assessment.
7. Every write sends the exact evaluation-result hash last read, requires a
   confirmation and then reloads the authoritative timeline. No event can be
   edited or deleted.

`no_alerts` and `no_active_rules` are never displayed as clearance. The inbox
does not diagnose, recommend, rank, authorize treatment, suppress findings,
notify external recipients or learn from patient records. See
`CLINICAL_SAFETY_INBOX.md` and `CLINICAL_SAFETY_ESCALATION_QUEUE.md` for the
complete contracts. Chronological queue order is not clinical priority.

## Role matrix

| Capability | admin | physician | nurse | operator | viewer |
| --- | --- | --- | --- | --- | --- |
| Live flow | yes | yes | yes | yes | no |
| Read clinical context | yes | yes | yes | API only | API only |
| Read evidence briefs in console | yes | yes | yes | no | no |
| Search approved facts in composer | no | yes | no | no | no |
| Create immutable evidence brief | no | yes | no | no | no |
| Read safety inbox | yes | yes | yes | no | no |
| Run deterministic safety evaluation | yes | yes | no | no | no |
| Acknowledge or escalate a finding | no | yes | yes | no | no |
| Record terminal finding assessment | no | yes | no | no | no |
| Read open-escalation queue | yes | yes | yes | no | no |

## Browser security contract

- Access tokens exist only in JavaScript memory. They are not written to cookies,
  local storage, session storage or IndexedDB. Refreshing or closing the page
  therefore requires a new login.
- The console and API are same-origin. Requests use no cross-origin credentials.
- HTML, CSS and JavaScript are local release assets; there are no third-party
  scripts, fonts or analytics.
- `/app` responses use `Cache-Control: no-store`, a restrictive Content Security
  Policy, frame denial, MIME sniffing protection, no referrer and disabled
  camera/location/microphone permissions.
- Patient, session and evidence values are inserted with `textContent`, not
  interpreted as markup.
- Approved-fact URLs and citations are rendered as inert text. The console does
  not navigate to untrusted source URLs or load third-party content.
- The server supplies the canonical clinical-context hash used for guarded
  evidence and safety requests; the browser does not reimplement clinical
  canonicalization.
- The page intentionally has no service worker, offline cache or browser push.

These controls reduce browser exposure but do not replace HTTPS, a reviewed
reverse proxy, managed workstations, short token lifetime, endpoint protection,
screen privacy, staff training or production penetration testing.

## Verification

The backend suite verifies the shell, evidence- and safety-workspace copy and
contracts, escalation lifecycle and minimization, role boundaries, stale-context
detection, same-origin assets, server-computed context digest, security headers,
absence of persistent browser token storage and continued API authentication.
CI additionally runs JavaScript syntax validation. The hardened container smoke
loads `/app/` and verifies that the packaged JavaScript is not cacheable.

This is an engineering gate, not clinician acceptance or a regulatory
determination. Before production use, validate Persian terminology, evidence
presentation, accessibility, supported browsers, real staff roles, workstation
handling and both workflows with synthetic data in the selected staging
environment. Safety-alert delivery, response-time policy and clinical
prioritization remain separate deployment and governance work.
