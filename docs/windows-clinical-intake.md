# Windows clinic installation: physician intake

The physician copilot now includes a Persian structured clinical intake editor.
It uses the existing API and schema; no new migration or dependency is needed.

## Patient flow

1. Open the visit in Reception and Consent, record the administrative intake,
   and assign an active physician account.
2. Sign in as the physician, select Physician Copilot, and load that visit.
3. Complete the clinical intake form, including the body region. Unknown pain
   remains empty; it is not converted to zero. Empty history/medication/allergy
   lists do not certify an absence of those conditions.
4. Save the draft. Review the saved values and check the explicit confirmation.
5. Finalize the intake. Copilot reloads the finalized context and roadmap.
6. A final intake is read-only. An explicit reason creates a correction draft;
   the previous final context remains effective until the correction is finalized.

Roadmap availability still depends on current safety evaluation, matching
approved protocols, and sufficient local outcome data. Finalizing an intake
does not manufacture comparison cases or authorize treatment.

## Existing local setup fixes

The release includes the canonical versions of the two temporary Windows fixes:
UTC conversion for persisted reception/consent timestamps and escaping percent
characters in the database URI when Alembic reads configuration.

Before pulling this release, stop Uvicorn with Ctrl+C. Preserve those local code
edits, if present, with:

```powershell
git stash push -m mos-local-setup-fixes -- backend/app/services/reception.py backend/migrations/env.py
git pull --ff-only origin main
.\.venv\Scripts\python.exe -m backend.tools.release_preflight
```

Do not reapply the stashed temporary fixes: this release contains them. The
stash remains available for comparison. This command does not stash `.env`.
If Git reports other local modifications, stop and inspect them rather than
discarding them. After successful preflight:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Refresh the browser with Ctrl+F5. The local address remains
http://127.0.0.1:8000/app/ .

## Concurrency and tests

The editor sends the saved intake digest using the optional `If-Match` header
on draft replacement and finalization. The backend compares it while holding
the visit write lock, rejecting stale edits or unreviewed finalizations.
Legacy API clients that omit the header retain their existing behavior.

UI behavior tests run using the pinned jsdom package in `backend/tests/ui`.
Regression tests cover UTC/Tehran timestamps, changed-content integrity,
actual percent-containing URI migration, stale intake updates/finalization,
session/visit clearing, explicit review, unknown pain, and correction drafts.
