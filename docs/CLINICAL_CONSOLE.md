# Clinical operations console

The first mobile-friendly staff interface is served from `/app/` by the same
FastAPI process as the API. It provides authenticated access to the existing
clinic live-flow projection and executes only workflow transitions returned by
the backend in each session's `allowed_actions` list.

This stage does not add a new clinical policy, database migration, patient-data
store, offline mode or public patient portal. The API remains the authorization
and validation boundary.

## Supported journey

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
- Patient/session values are inserted with `textContent`, not interpreted as
  markup.
- The page intentionally has no service worker, offline cache or browser push.

These controls reduce browser exposure but do not replace HTTPS, a reviewed
reverse proxy, managed workstations, short token lifetime, endpoint protection,
screen privacy, staff training or production penetration testing.

## Verification

The backend suite verifies the shell, same-origin assets, security headers,
absence of persistent browser token storage and continued API authentication.
CI additionally runs JavaScript syntax validation. The hardened container smoke
loads `/app/` and verifies that the packaged JavaScript is not cacheable.

This is an engineering gate, not clinician acceptance. Before production use,
validate Persian terminology, accessibility, supported browsers, real staff
roles, workstation handling and the full clinic workflow with synthetic data in
the selected staging environment.
