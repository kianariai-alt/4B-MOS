# Governed Protocol Recovery and Lineage

Stage 24 adds an explicit, append-only recovery workflow for already executed
governed protocol releases.

Recovery never deletes or rewrites the original release. It creates new
governance evidence that points back to the exact release being reversed.

## Recovery case creation

A recovery case starts from an existing release:

`POST /api/v1/protocol-governance/releases/{release_id}/recovery-cases`

Only an active physician may open the case.

The request must include:

- the exact source-release SHA-256;
- the current Clinical Learning Review SHA-256;
- a clinical rationale;
- optional evidence or data still required.

The caller does not choose the recovery action.

The backend derives it from the immutable source release:

- a `deactivate` release creates a `reactivation_candidate`;
- a `publish_revision` release creates a
  `rollback_revision_candidate`.

The case freezes the source release, current protocol state, current learning
review and recovery target state.

## Independent review remains mandatory

Recovery cases use the same independent governance chain as ordinary protocol
cases:

1. case author is a physician;
2. a different physician performs clinical review;
3. an administrator performs operational acknowledgement;
4. only then can an administrator execute recovery.

Approval alone does not change protocol state.

## Recovery execution

`POST /api/v1/protocol-governance/cases/{case_id}/recovery`

Only an active administrator may execute recovery.

Immediately before mutation the backend re-validates:

- case integrity;
- source-release integrity and SHA-256;
- complete clinical and operational approval;
- frozen protocol snapshots;
- release lineage;
- expected active/inactive state;
- absence of another active version for the same protocol code;
- absence of an already executed recovery for the same release.

Any mismatch requires a new governance case.

## Reactivation

For a prior governed deactivation, recovery reactivates the exact protocol
version that the release deactivated.

No new protocol row is created and no history is removed.

## Revision rollback

For a prior governed revision release, recovery:

1. verifies that the released revision is still the active child created by that
   exact release;
2. verifies that the superseded version is still inactive;
3. deactivates the released revision;
4. reactivates the superseded version;
5. preserves the original revision row and all release provenance.

This is a new governed event, not a destructive database rollback.

## Immutable recovery evidence

Each recovery record freezes:

- recovery case ID and SHA-256;
- source release ID and SHA-256;
- action;
- deactivated protocol ID when applicable;
- reactivated protocol ID;
- before snapshots;
- after snapshots;
- administrator identity;
- execution note;
- timestamp;
- recovery SHA-256.

Each source release can be recovered at most once.

## Lineage view

`GET /api/v1/protocol-governance/protocols/{protocol_id}/lineage`

The read-only lineage response includes:

- every registered version for the protocol code;
- governed releases touching those versions;
- governed recoveries touching those versions;
- the currently active protocol ID, if any.

The service rejects a lineage with conflicting treatment types or more than one
active version.

The lineage view is descriptive. It never chooses a protocol for a patient.

## Clinical boundary

Recovery is execution of a fully reviewed human governance decision.

The system does not decide that a prior protocol was better, does not infer a
rollback from outcomes, does not reactivate a protocol automatically and does
not use local observational outcomes as causal proof.
