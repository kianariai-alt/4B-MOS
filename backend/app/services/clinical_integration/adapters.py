"""Adapters to current finalized 4B-MOS records, without new medical inference."""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.models.user import User
from backend.app.schemas.clinical_context import ClinicalContextRead, ParaclinicalObservationInput
from backend.app.schemas.clinical_integration import (
    ClinicalAssessmentReference, ComponentVersion, CoreFinding, CoreInput, CoreOutput,
    ImagingStudyReference, IntegrationIssue, KnowledgeReference, PhysicianApproval, RecordReference,
    SourceObservation,
)
from backend.app.services.clinical_integration.engine import MAX_RUN_AGE, digest_model
from backend.app.services.medical_knowledge import MedicalKnowledgeService
from backend.app.services.session_finalization import evidence_digest


def utc(value: datetime) -> datetime:
    # SQLite drops timezone metadata; application timestamps are stored in UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


@dataclass(frozen=True)
class SourceBundle:
    core_input: CoreInput
    assessment: ClinicalAssessmentReference | None
    studies: tuple[ImagingStudyReference, ...]
    approvals: dict[str, PhysicianApproval]
    issues: tuple[IntegrationIssue, ...]


def source_bundle(db: Session, context: ClinicalContextRead, context_sha256: str) -> SourceBundle:
    observations, studies, approvals, issues = [], [], {}, []

    def append(record, ref, observation):
        observations.append(SourceObservation(source=ref, observation=observation))
        # Finality alone is not physician review: existing record finalizers may
        # be administrators. Resolve authoritative attribution on the server.
        reviewer = db.get(User, record.finalized_by_user_id) if record.finalized_by_user_id else None
        if reviewer is not None and reviewer.role == "physician" and record.finalized_at:
            approvals[digest_model(ref)] = PhysicianApproval(
                physician_user_id=reviewer.id, reviewed_at=utc(record.finalized_at),
            )

    assessment = None
    intake = context.intake
    if intake is not None:
        assessment = ClinicalAssessmentReference(
            intake_id=intake.id, version=intake.version, content_sha256=intake.content_sha256,
            body_region=intake.body_region, laterality=intake.laterality,
        )
        for field, observation in (
            ("exam_findings", ParaclinicalObservationInput(
                category="clinical_test", code_system="LOCAL", code="INTAKE_EXAM",
                display_name="Recorded examination", value_type="string",
                string_value=intake.exam_findings, body_site=intake.body_region,
            ) if intake.exam_findings else None),
            ("pain_score", ParaclinicalObservationInput(
                category="clinical_test", code_system="LOCAL", code="INTAKE_PAIN_0_10",
                display_name="Recorded pain score", value_type="integer",
                integer_value=intake.pain_score, body_site=intake.body_region,
            ) if intake.pain_score is not None else None),
        ):
            if observation is not None:
                append(intake, RecordReference(
                    record_type="clinical_intake", record_id=intake.id, version=intake.version,
                    content_sha256=intake.content_sha256, field=field,
                ), observation)
    for report in context.reports:
        if report.category == "imaging":
            studies.append(ImagingStudyReference(
                report_id=report.id, version=report.version, content_sha256=report.content_sha256,
            ))
        for observation in report.observations:
            # Imaging report category cannot silently promote non-imaging data.
            if (report.category == "imaging") != (observation.category == "imaging"):
                issues.append(IntegrationIssue(code="report_observation_category_mismatch", severity="blocking"))
                continue
            value = ParaclinicalObservationInput.model_validate(
                observation.model_dump(exclude={"id", "sort_order", "created_at"})
            )
            append(report, RecordReference(
                record_type="paraclinical_report", record_id=report.id, version=report.version,
                content_sha256=report.content_sha256, observation_id=observation.id,
                field="observation",
            ), value)
    return SourceBundle(
        core_input=CoreInput(visit_id=context.visit_id, clinical_context_sha256=context_sha256,
                             observations=tuple(observations)),
        assessment=assessment, studies=tuple(studies), approvals=approvals, issues=tuple(issues),
    )


class FinalRecordAdapter:
    """Passthrough adapter only. Does not implement either specialist core."""

    def __init__(self, core: str):
        self.core = core

    def current_version(self) -> ComponentVersion:
        return ComponentVersion(
            component_id=f"4b-{self.core}-final-records", version="1.0.0", kind="adapter",
            artifact_sha256=evidence_digest({"adapter": self.core, "mapping_version": 1}),
        )

    def collect(self, context: CoreInput) -> CoreOutput:
        now = datetime.now(timezone.utc)
        observations = [item for item in context.observations
                        if (item.observation.category == "imaging") == (self.core == "imaging")]
        return CoreOutput(
            core=self.core, visit_id=context.visit_id,
            clinical_context_sha256=context.clinical_context_sha256,
            component=self.current_version(), generated_at=now, valid_until=now + MAX_RUN_AGE,
            status="available" if observations else "missing",
            findings=tuple(CoreFinding(
                finding_id=digest_model(item.source), source=item.source,
                observation=item.observation, origin="record",
            ) for item in observations),
        )


def local_adapters():
    return {core: FinalRecordAdapter(core) for core in ("orthopedic", "imaging")}


def approved_knowledge(db: Session, ids: tuple[str, ...], *, as_of, lock=False) -> tuple[KnowledgeReference, ...]:
    refs = []
    for fact_id in sorted(ids):
        fact = MedicalKnowledgeService.get(db, fact_id, for_share=lock)
        if (fact.status != "approved" or not fact.reviewed_by_user_id or not fact.reviewed_at
                or (fact.valid_from and fact.valid_from > as_of)
                or (fact.valid_to and fact.valid_to < as_of)):
            raise ValueError("Selected knowledge is not currently approved and valid.")
        refs.append(KnowledgeReference(
            fact_id=fact.id, fact_key=fact.fact_key, version=fact.version,
            content_sha256=fact.content_sha256, evidence_grade=fact.evidence_grade,
            source_ids=tuple(source.id for source in fact.sources),
            valid_from=fact.valid_from, valid_to=fact.valid_to,
        ))
    return tuple(refs)
