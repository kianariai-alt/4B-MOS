# API release acceptance

This is an automated engineering acceptance scenario for the backend API. It
uses only synthetic records in a disposable test database. Passing it does not
approve a production migration, validate a clinical protocol or certify a user
interface.

## Covered journey

`backend/tests/test_release_acceptance.py` crosses the public HTTP boundary and
verifies one coherent clinic journey with separate role credentials:

1. An administrator creates a versioned ACS protocol and a lot-tracked material.
2. An operator registers a synthetic patient and opens a visit.
3. A physician creates a protocol-linked treatment and planned component.
4. The operator, nurse and physician advance the session through check-in,
   readiness and active treatment.
5. The nurse records a plan-linked administration with lot and expiry data.
6. A viewer reads variance, clinical summary and completion readiness.
7. The nurse completes the session and the API captures versioned finalization
   evidence with a valid SHA-256 integrity checksum.
8. Direct edits and late administration writes are refused after completion.
9. The nurse adds an append-only supplement and a different physician approves
   it without changing the original finalization evidence.
10. Discharge, patient summary, timeline and session audit history remain
    mutually coherent.

The suite also verifies that release-critical OpenAPI paths remain present and
that every generated operation ID is unique. This catches accidental router
omission and operation-name collisions before an API client is generated.

## Run the gate

From the repository root, using the same isolated environment as the backend:

```sh
python -m pytest backend/tests/test_release_acceptance.py -q
```

The complete required verification remains:

```sh
python -m pytest backend/tests -q
python -m alembic heads
python -m alembic check
```

Pull requests run the complete suite against disposable SQLite databases on
Python 3.12 and 3.14. The existing PostgreSQL CI matrix separately exercises
the database-specific locking and concurrency paths.

## Deliberate limitations

- The journey does not use or connect to production or identifiable patient
  data.
- It validates the existing clinical rules; it does not introduce or approve
  new treatment policy.
- It does not test browser/mobile presentation, accessibility, device support,
  notification delivery, external identity providers or deployment topology.
- It is not a load, failover, penetration, backup-restore or managed-database
  certification.
- SHA-256 remains an integrity check, not a digital or legal signature.
