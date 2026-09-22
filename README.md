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

The [clinician-selected clinical evidence brief](docs/CLINICAL_EVIDENCE_BRIEFS.md)
lets a physician preserve approved, source-linked knowledge beside one exact
final clinical-context snapshot. Selection is manual and every response remains
explicitly non-recommendation, non-ranking, non-clearance and subject to
independent physician review. It does not infer applicability or learn from
patient records. The clinical console exposes this workflow without weakening
the same role, hash, immutability or independent-review controls.
