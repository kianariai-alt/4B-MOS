# Governed Protocol Release

Stage 23 turns an approved Protocol Governance case into an explicit, auditable
protocol-registry mutation.

The release action is deliberately separate from clinical and operational
review. Approval alone never changes a protocol.

## Release endpoint

`POST /api/v1/protocol-governance/cases/{case_id}/release`

Only an active administrator may execute a release.

The request must include:

- the exact governance-case SHA-256;
- a human execution note.

The backend determines the permitted release action from the immutable case
type. The caller cannot substitute another action.

## Eligible case types

### revision_candidate

A fully approved revision candidate publishes the exact proposed protocol
snapshot frozen in the Governance Case.

The transaction:

1. verifies that the source protocol still matches the frozen case snapshot;
2. verifies that the proposed code/version does not already exist;
3. creates the new active protocol version;
4. freezes lineage to the superseded protocol ID and governance case ID/hash;
5. deactivates the source version;
6. records an immutable governed-release record and audit events;
7. commits the entire mutation atomically.

If any write fails, the transaction rolls back.

### deactivation_candidate

A fully approved deactivation candidate deactivates the exact frozen source
protocol and records the immutable governed-release evidence in the same
transaction.

## Non-release case types

`collect_more_data` and `monitor_no_change` can never execute a protocol
release, even after clinical and operational acknowledgement.

## One case, one release

Each Governance Case can create at most one release record.

The database enforces a unique case-to-release relationship and the service
rejects repeated execution attempts.

## Release evidence

Each immutable release record freezes:

- governance case ID and SHA-256;
- action;
- source protocol ID;
- source protocol snapshot before execution;
- source protocol snapshot after execution;
- newly released protocol ID when applicable;
- newly released protocol snapshot when applicable;
- administrator identity;
- execution note;
- timestamp;
- release SHA-256.

Governance case reads expose the release record and derive the terminal
`released` state.

## Protocol lineage

A governed revision stores on the new protocol row:

- `supersedes_protocol_id`;
- `source_governance_case_id`;
- `source_governance_case_sha256`.

This allows registry-only inspection to retain provenance without needing to
reconstruct it from application logs.

## Governance enforcement

After Stage 23:

- the first version of a new protocol code may still be registered normally;
- additional versions of an existing code cannot be created through the normal
  protocol-create endpoint;
- protocol deactivation cannot be performed through the normal delete endpoint;
- revision publication and deactivation require the approved governed-release
  path.

This prevents the governance workflow from being bypassed by an ordinary API
write.

## Rollback semantics

A governed release is historical evidence and is never deleted or rewritten.

Stage 23 does not implement a destructive rollback. A future reversal or
reactivation must be represented as another explicit governed action so the
original release remains visible.

## Clinical boundary

The release service executes an already approved human governance decision. It
does not decide that a protocol should change, does not infer new parameters,
does not compare treatment effectiveness, and does not promote a protocol based
on local outcomes by itself.
