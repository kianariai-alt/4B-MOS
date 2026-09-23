# 4B-MOS backend

FastAPI/SQLAlchemy clinic workflow backend. This repository is not yet a complete
deployed clinic product. Do not expose development defaults to the internet.

Completed-session evidence remains immutable. Any later correction or supplement
is stored as a separate append-only amendment with an immutable review decision;
the original finalization record is never rewritten.

Known accounts have persistent, account-bound login throttling. Failed login
responses do not distinguish a missing, inactive, locked or wrong-password
account. This backend control does not replace HTTPS, edge/source throttling,
alerting or a reviewed security-monitoring and retention program.

Install dependencies in an isolated environment and verify from the repository root:

```sh
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m pytest backend/tests -q
```

Pull requests additionally migrate a disposable PostgreSQL 18 database and run
the PostgreSQL-specific isolation, row/table-lock, timeout, deadlock and amendment
sequence tests on Python 3.12 and 3.14. No external or production database is used.

See [release readiness](docs/RELEASE_READINESS.md) for clinical limitations and
[the operations runbook](docs/OPERATIONS_RUNBOOK.md) for staged installation,
production settings, explicit-path SQLite backups and new-copy upgrade rehearsals.
No production migration or server deployment is performed by the test command.

The [API release-acceptance gate](docs/RELEASE_ACCEPTANCE.md) exercises one
synthetic, role-separated journey from registration through finalization,
append-only amendment review, discharge and audit verification.

Before a controlled deployment, the [release preflight](docs/RELEASE_PREFLIGHT.md)
provides a redacted, read-only check of production runtime settings, database
schema readiness and active-administrator availability. It does not deploy or
migrate anything and is not production authorization.

The root [production container artifact](docs/CONTAINER_RELEASE.md) runs as a
non-root user and is build/smoke-tested by CI with a read-only root filesystem.
It remains deployment-provider neutral and never migrates on normal startup.

The [mobile-friendly clinical console](docs/CLINICAL_CONSOLE.md) is available at
`/app/`. It uses the existing role-protected live-flow and workflow APIs, gives
physicians a manual evidence-review workspace, and exposes the existing
deterministic safety findings through a role-gated
[clinical safety inbox](docs/CLINICAL_SAFETY_INBOX.md). It keeps its bearer token
in memory only, preselects no evidence and adds no offline patient-data store.
It remains subject to clinician, accessibility and production acceptance.

The [medical knowledge registry](docs/MEDICAL_KNOWLEDGE_REGISTRY.md) stores
source-linked, versioned facts behind an independent clinical review gate.
Only approved, currently valid versions are exposed to future decision-support
consumers. It does not learn from patient records, ingest new research, or make
diagnostic or treatment recommendations by itself.

The [structured clinical context](docs/STRUCTURED_CLINICAL_CONTEXT.md) stores a
versioned initial intake and typed paraclinical observations. Final records are
immutable through the API; corrections are linked replacement versions. Patient
records never become general medical knowledge automatically, and this stage
still produces no diagnostic or treatment recommendation.

The [clinical safety rule engine](docs/CLINICAL_SAFETY_RULE_ENGINE.md) evaluates
only approved, source-linked rules against that current final context and stores
append-only, explainable snapshots. It can flag configured conditions for
physician review; `no_alerts` is never clearance, and the engine does not
diagnose, prescribe, rank treatments, or learn automatically from patient data.

The [clinical safety finding review workflow](docs/CLINICAL_SAFETY_REVIEW_WORKFLOW.md)
adds hash-chained, append-only acknowledgment, escalation and physician-assessment
events for those findings. Review events never rewrite an evaluation, suppress a
finding, grant clearance or update medical knowledge from patient data.
The console inbox preserves those same hashes, roles and append-only transitions;
it is a workflow surface, not a diagnostic or recommendation engine.
The [clinical safety escalation queue](docs/CLINICAL_SAFETY_ESCALATION_QUEUE.md)
adds a minimal cross-visit view of findings whose latest verified event is an
escalation. Its oldest-first order is administrative, not clinical prioritization,
and it sends no external notification or response-time promise.

The [physician copilot snapshot](docs/PHYSICIAN_COPILOT_SNAPSHOT.md) assembles
the current structured context, latest safety inbox, current-evaluation
escalations and immutable clinician-selected evidence briefs into one read-only,
hash-bound physician view. It does not diagnose, recommend, rank treatments,
calculate a patient risk score or grant clinical clearance.

The [clinical outcomes registry](docs/CLINICAL_OUTCOMES_REGISTRY.md) records
append-only, provenance-bound treatment follow-up observations after at least one
completed session has immutable finalization evidence. Patient and physician
ratings remain separate, protocol/context/finalization hashes are preserved, and
the registry is explicitly observational rather than causal evidence. These
records are also visible in the physician copilot as longitudinal follow-up
history. The registry itself does not learn or recommend treatment.

The [similar-patient treatment options roadmap](docs/SIMILAR_PATIENT_TREATMENT_ROADMAP.md)
uses those immutable outcomes to build a transparent local cohort for a current
visit after the current safety workflow is satisfied. It can expose multiple
reviewable active-protocol options with sample size, follow-up windows, observed
outcomes, separate patient/physician ratings and uncertainty. It does not rank,
select, prescribe or grant clinical clearance, and local observations are not
treated as causal evidence.

The [clinician decision and learning feedback loop](docs/CLINICIAN_DECISION_FEEDBACK_LOOP.md)
records the physician's explicit selection, modification, combination, outside-
roadmap choice, deferral or no-treatment decision against an exact roadmap hash.
Decisions are append-only, Treatments can freeze the decision ID/hash, and later
Outcomes remain traceable through the frozen Treatment snapshot. The feedback
loop does not automatically rewrite protocols or convert local outcomes into
autonomous treatment policy.

The [clinical learning review](docs/CLINICAL_LEARNING_REVIEW.md) audits whether
that local feedback dataset is actually complete enough to support responsible
learning. It reports Decision/Treatment/Outcome linkage, follow-up-window counts,
field completeness and per-protocol data volume without creating an
effectiveness league table, composite learning score or automatic protocol
change.

The [protocol learning governance workspace](docs/PROTOCOL_LEARNING_GOVERNANCE.md)
adds descriptive data-quality signals and append-only governance cases for exact
protocol versions. Independent physician review and separate operational
acknowledgement are preserved, while even a fully reviewed case remains only
approved for manual action and never changes a protocol automatically.

The [governed protocol release](docs/GOVERNED_PROTOCOL_RELEASE.md) requires a
separate explicit administrator execution after full governance approval.
Revision releases atomically publish the frozen new version, deactivate the
superseded source version and preserve registry lineage; deactivation releases
atomically retire the approved source version. Ordinary API writes can no longer
create later versions or deactivate protocols outside this governance path.

The [governed protocol recovery and lineage](docs/GOVERNED_PROTOCOL_RECOVERY.md)
adds a separate recovery case for an exact prior release. A deactivation may be
reactivated and a revision release may be rolled back only after a new
independent physician review and administrator acknowledgement. The original
release remains immutable, recovery is recorded as a new append-only event, and
the lineage API rejects multiple simultaneously active versions.

The [clinician-selected clinical evidence brief](docs/CLINICAL_EVIDENCE_BRIEFS.md)
lets a physician preserve approved, source-linked knowledge beside one exact
final clinical-context snapshot. Selection is manual and every response remains
explicitly non-recommendation, non-ranking, non-clearance and subject to
independent physician review. It does not infer applicability or learn from
patient records. The clinical console exposes this workflow without weakening
the same role, hash, immutability or independent-review controls.
