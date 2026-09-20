"""Transparent evidence snapshots selected by a physician for one visit."""

from copy import deepcopy
from datetime import date, datetime, timezone
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.audit_log import AuditLog
from backend.app.models.clinical_context import ClinicalIntake, ParaclinicalReport
from backend.app.models.clinical_evidence import ClinicalEvidenceBrief
from backend.app.models.medical_knowledge import MedicalKnowledgeFact
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.clinical_evidence import (
    ClinicalEvidenceBriefRepository,
)
from backend.app.repositories.medical_knowledge import MedicalKnowledgeRepository
from backend.app.repositories.visit import VisitRepository
from backend.app.schemas.clinical_evidence import (
    ClinicalEvidenceBriefCreate,
    ClinicalEvidenceBriefPayloadRead,
    ClinicalEvidenceBriefRead,
    EvidenceBriefContextManifest,
    EvidenceBriefFactSnapshot,
    EvidenceBriefRecordReference,
    EvidenceBriefSourceSnapshot,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.clinical_context import (
    ClinicalContextIntegrityError,
    ClinicalContextNotFoundError,
    ClinicalContextService,
)
from backend.app.services.clinical_safety import clinical_context_digest
from backend.app.services.medical_knowledge import (
    MedicalKnowledgeIntegrityError,
    MedicalKnowledgeService,
)
from backend.app.services.session_finalization import evidence_digest


CREATE_ROLES = {"physician"}
KNOWN_LIMITATIONS = [
    "No diagnosis, recommendation, treatment ranking, dosage, prognosis, risk "
    "score, follow-up directive, or clinical clearance is produced.",
    "The physician selected the facts; the system did not infer patient-specific "
    "applicability or relevance.",
    "Population fit, indications, contraindications, completeness, source "
    "currency, and conflicts between sources require independent review.",
    "This evidence summary is not intended for time-critical decision-making.",
    "Terminology semantics and measurement-unit conversions are not validated by "
    "this workflow.",
]


class ClinicalEvidenceNotFoundError(Exception):
    pass


class ClinicalEvidenceConflictError(Exception):
    pass


class ClinicalEvidenceAuthorizationError(Exception):
    pass


class ClinicalEvidenceIntegrityError(Exception):
    pass


def _same_timestamp(payload_value: str, column_value: datetime) -> bool:
    try:
        parsed = datetime.fromisoformat(payload_value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    if column_value.tzinfo is None:
        column_value = column_value.replace(tzinfo=timezone.utc)
    else:
        column_value = column_value.astimezone(timezone.utc)
    return parsed == column_value


def clinical_evidence_knowledge_set_digest(
    facts: list[MedicalKnowledgeFact],
) -> str:
    return evidence_digest(
        {
            "schema_version": 1,
            "ordering": "fact_key_then_version",
            "facts": [
                {
                    "id": fact.id,
                    "fact_key": fact.fact_key,
                    "version": fact.version,
                    "content_sha256": fact.content_sha256,
                }
                for fact in facts
            ],
        }
    )


class ClinicalEvidenceBriefService:
    @staticmethod
    def _require_actor(actor: User | None) -> User:
        if (
            actor is None
            or not actor.is_active
            or actor.role not in CREATE_ROLES
        ):
            raise ClinicalEvidenceAuthorizationError(
                "Only an active physician may create a clinical evidence brief."
            )
        return actor

    @staticmethod
    def _context_manifest_from_read(context) -> EvidenceBriefContextManifest:
        if context.intake is None:
            raise ClinicalEvidenceConflictError(
                "A final clinical intake is required before creating an evidence "
                "brief."
            )
        return EvidenceBriefContextManifest(
            intake=EvidenceBriefRecordReference(
                id=context.intake.id,
                record_type="clinical_intake",
                record_key=None,
                version=context.intake.version,
                content_sha256=context.intake.content_sha256,
            ),
            reports=[
                EvidenceBriefRecordReference(
                    id=report.id,
                    record_type="paraclinical_report",
                    record_key=report.report_key,
                    version=report.version,
                    content_sha256=report.content_sha256,
                )
                for report in context.reports
            ],
        )

    @staticmethod
    def _context_manifest_from_records(
        intake: ClinicalIntake,
        reports: list[ParaclinicalReport],
    ) -> EvidenceBriefContextManifest:
        return EvidenceBriefContextManifest(
            intake=EvidenceBriefRecordReference(
                id=intake.id,
                record_type="clinical_intake",
                record_key=None,
                version=intake.version,
                content_sha256=intake.content_sha256,
            ),
            reports=[
                EvidenceBriefRecordReference(
                    id=report.id,
                    record_type="paraclinical_report",
                    record_key=report.report_key,
                    version=report.version,
                    content_sha256=report.content_sha256,
                )
                for report in reports
            ],
        )

    @staticmethod
    def _fact_snapshot(
        fact: MedicalKnowledgeFact,
    ) -> EvidenceBriefFactSnapshot:
        return EvidenceBriefFactSnapshot(
            id=fact.id,
            fact_key=fact.fact_key,
            version=fact.version,
            title=fact.title,
            statement=fact.statement,
            clinical_domain=fact.clinical_domain,
            therapy_type=fact.therapy_type,
            population=fact.population,
            indication=fact.indication,
            contraindications=list(fact.contraindications),
            evidence_grade=fact.evidence_grade,
            content_sha256=fact.content_sha256,
            valid_from=fact.valid_from,
            valid_to=fact.valid_to,
            sources=[
                EvidenceBriefSourceSnapshot(
                    source_type=source.source_type,
                    title=source.title,
                    citation=source.citation,
                    publisher=source.publisher,
                    url=source.url,
                    doi=source.doi,
                    publication_date=source.publication_date,
                    guideline_version=source.guideline_version,
                    accessed_at=source.accessed_at,
                )
                for source in fact.sources
            ],
        )

    @staticmethod
    def _load_current_fact(
        db: Session,
        fact_id: str,
        *,
        expected_content_sha256: str,
        as_of: date,
    ) -> MedicalKnowledgeFact:
        fact = MedicalKnowledgeRepository.get_by_id(
            db,
            fact_id,
            for_share=True,
        )
        if fact is None:
            raise ClinicalEvidenceNotFoundError(
                f"Medical knowledge fact '{fact_id}' was not found."
            )
        try:
            MedicalKnowledgeService._verify(fact)
        except MedicalKnowledgeIntegrityError as error:
            raise ClinicalEvidenceIntegrityError(str(error)) from error
        if (
            fact.status != "approved"
            or (fact.valid_from is not None and fact.valid_from > as_of)
            or (fact.valid_to is not None and fact.valid_to < as_of)
        ):
            raise ClinicalEvidenceConflictError(
                f"Medical knowledge fact '{fact_id}' is not currently approved "
                "and valid."
            )
        if fact.content_sha256 != expected_content_sha256:
            raise ClinicalEvidenceConflictError(
                f"Medical knowledge fact '{fact_id}' changed; reload approved "
                "knowledge before creating the brief."
            )
        return fact

    @staticmethod
    def _load_historical_context(
        db: Session,
        brief: ClinicalEvidenceBrief,
    ) -> tuple[ClinicalIntake, list[ParaclinicalReport]]:
        intake = db.get(ClinicalIntake, brief.intake_id)
        reports = [db.get(ParaclinicalReport, item) for item in brief.report_ids]
        if (
            intake is None
            or intake.visit_id != brief.visit_id
            or any(report is None for report in reports)
            or any(report.visit_id != brief.visit_id for report in reports)
        ):
            raise ClinicalEvidenceIntegrityError(
                "Stored clinical evidence brief references missing or mismatched "
                "clinical records."
            )
        try:
            ClinicalContextService._verify_intake(intake)
            for report in reports:
                ClinicalContextService._verify_report(report)
        except ClinicalContextIntegrityError as error:
            raise ClinicalEvidenceIntegrityError(str(error)) from error
        return intake, reports

    @staticmethod
    def _load_historical_facts(
        db: Session,
        brief: ClinicalEvidenceBrief,
    ) -> list[MedicalKnowledgeFact]:
        facts: list[MedicalKnowledgeFact] = []
        for fact_id in brief.knowledge_fact_ids:
            fact = MedicalKnowledgeRepository.get_by_id(db, fact_id)
            if fact is None:
                raise ClinicalEvidenceIntegrityError(
                    "Stored clinical evidence brief references missing knowledge."
                )
            try:
                MedicalKnowledgeService._verify(fact)
            except MedicalKnowledgeIntegrityError as error:
                raise ClinicalEvidenceIntegrityError(str(error)) from error
            facts.append(fact)
        return facts

    @staticmethod
    def _validate(
        db: Session,
        brief: ClinicalEvidenceBrief,
    ) -> ClinicalEvidenceBriefPayloadRead:
        try:
            raw = brief.payload
            payload = ClinicalEvidenceBriefPayloadRead.model_validate(
                deepcopy(raw)
            )
            intake, reports = ClinicalEvidenceBriefService._load_historical_context(
                db,
                brief,
            )
            facts = ClinicalEvidenceBriefService._load_historical_facts(
                db,
                brief,
            )
            expected_manifest = (
                ClinicalEvidenceBriefService._context_manifest_from_records(
                    intake,
                    reports,
                )
            )
            expected_context_hash = evidence_digest(
                {
                    "schema_version": 1,
                    "visit_id": brief.visit_id,
                    "intake": {
                        "id": intake.id,
                        "content_sha256": intake.content_sha256,
                    },
                    "reports": [
                        {
                            "id": report.id,
                            "report_key": report.report_key,
                            "content_sha256": report.content_sha256,
                        }
                        for report in reports
                    ],
                }
            )
            expected_snapshots = [
                ClinicalEvidenceBriefService._fact_snapshot(fact).model_dump(
                    mode="json"
                )
                for fact in facts
            ]
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == brief.sha256
                and payload.id == brief.id
                and payload.visit_id == brief.visit_id
                and payload.selection_method == brief.selection_method
                and payload.output_type == brief.output_type
                and payload.knowledge_as_of == brief.knowledge_as_of
                and payload.clinical_context_sha256
                == brief.clinical_context_sha256
                == expected_context_hash
                and payload.context_manifest.model_dump(mode="json")
                == expected_manifest.model_dump(mode="json")
                and [item.id for item in payload.facts]
                == brief.knowledge_fact_ids
                and [item.model_dump(mode="json") for item in payload.facts]
                == expected_snapshots
                and payload.knowledge_set_sha256
                == brief.knowledge_set_sha256
                == clinical_evidence_knowledge_set_digest(facts)
                and payload.known_limitations == KNOWN_LIMITATIONS
                and payload.actor.actor_user_id == brief.created_by_user_id
                and _same_timestamp(payload.created_at, brief.created_at)
            )
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
        ):
            valid = False
            payload = None
        if not valid or payload is None:
            raise ClinicalEvidenceIntegrityError(
                "Stored clinical evidence brief failed its integrity check."
            )
        return payload

    @staticmethod
    def _to_read(
        db: Session,
        brief: ClinicalEvidenceBrief,
    ) -> ClinicalEvidenceBriefRead:
        payload = ClinicalEvidenceBriefService._validate(db, brief)
        return ClinicalEvidenceBriefRead(
            id=brief.id,
            visit_id=brief.visit_id,
            intake_id=brief.intake_id,
            report_ids=list(brief.report_ids),
            clinical_context_sha256=brief.clinical_context_sha256,
            knowledge_fact_ids=list(brief.knowledge_fact_ids),
            knowledge_set_sha256=brief.knowledge_set_sha256,
            knowledge_as_of=brief.knowledge_as_of,
            selection_method=brief.selection_method,
            output_type=brief.output_type,
            created_by_user_id=brief.created_by_user_id,
            sha256=brief.sha256,
            created_at=brief.created_at,
            payload=payload,
        )

    @staticmethod
    @clinical_record_write
    def create(
        db: Session,
        visit_id: str,
        payload: ClinicalEvidenceBriefCreate,
        *,
        actor: User | None,
    ) -> ClinicalEvidenceBriefRead:
        actor = ClinicalEvidenceBriefService._require_actor(actor)
        if VisitRepository.get_by_id(db, visit_id) is None:
            raise ClinicalEvidenceNotFoundError(
                f"Visit '{visit_id}' was not found."
            )
        try:
            context = ClinicalContextService.get_current_context(db, visit_id)
        except ClinicalContextNotFoundError as error:
            raise ClinicalEvidenceNotFoundError(str(error)) from error
        except ClinicalContextIntegrityError as error:
            raise ClinicalEvidenceIntegrityError(str(error)) from error
        manifest = ClinicalEvidenceBriefService._context_manifest_from_read(
            context
        )
        context_hash = clinical_context_digest(context)
        if payload.expected_clinical_context_sha256 != context_hash:
            raise ClinicalEvidenceConflictError(
                "The clinical context changed; reload it before selecting evidence."
            )

        knowledge_as_of = datetime.now(timezone.utc).date()
        expected_hashes = {
            item.fact_id: item.expected_content_sha256 for item in payload.facts
        }
        facts = [
            ClinicalEvidenceBriefService._load_current_fact(
                db,
                fact_id,
                expected_content_sha256=expected_hash,
                as_of=knowledge_as_of,
            )
            for fact_id, expected_hash in expected_hashes.items()
        ]
        facts.sort(key=lambda item: (item.fact_key, item.version, item.id))
        knowledge_hash = clinical_evidence_knowledge_set_digest(facts)
        brief_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        stored_payload = ClinicalEvidenceBriefPayloadRead(
            schema_version=1,
            id=brief_id,
            visit_id=visit_id,
            clinical_question=payload.clinical_question,
            intended_user="physician",
            intended_use="independent_evidence_review",
            selection_method="clinician_selected",
            ordering="fact_key_then_version",
            output_type="evidence_summary",
            knowledge_as_of=knowledge_as_of,
            clinical_context_sha256=context_hash,
            context_manifest=manifest,
            knowledge_set_sha256=knowledge_hash,
            facts=[
                ClinicalEvidenceBriefService._fact_snapshot(fact)
                for fact in facts
            ],
            known_limitations=list(KNOWN_LIMITATIONS),
            actor=actor_data(actor),
            created_at=created_at.isoformat(),
        ).model_dump(mode="json")
        sha256 = evidence_digest(stored_payload)
        brief = ClinicalEvidenceBriefRepository.create(
            db,
            brief_id=brief_id,
            visit_id=visit_id,
            intake_id=context.intake.id,
            report_ids=[report.id for report in context.reports],
            clinical_context_sha256=context_hash,
            knowledge_fact_ids=[fact.id for fact in facts],
            knowledge_set_sha256=knowledge_hash,
            knowledge_as_of=knowledge_as_of,
            created_by_user_id=actor.id,
            payload=stored_payload,
            sha256=sha256,
            created_at=created_at,
        )
        AuditLogRepository.create(
            db,
            commit=False,
            entity_type="clinical_evidence_brief",
            entity_id=brief.id,
            event_type="clinical_evidence_brief_created",
            from_state=None,
            to_state="immutable",
            message=(
                "A physician-selected, append-only clinical evidence summary "
                "was recorded for independent review."
            ),
            event_data={
                "visit_id": visit_id,
                "clinical_context_sha256": context_hash,
                "knowledge_set_sha256": knowledge_hash,
                "knowledge_fact_count": len(facts),
                "brief_sha256": sha256,
                "selection_method": "clinician_selected",
                "output_type": "evidence_summary",
                "is_recommendation": False,
                "ranks_treatments": False,
                "provides_risk_score": False,
                "is_clinical_clearance": False,
                "is_time_critical": False,
                "requires_independent_review": True,
            },
            **actor_data(actor),
        )
        return ClinicalEvidenceBriefService._to_read(db, brief)

    @staticmethod
    def get(
        db: Session,
        brief_id: str,
    ) -> ClinicalEvidenceBriefRead:
        brief = ClinicalEvidenceBriefRepository.get_by_id(db, brief_id)
        if brief is None:
            raise ClinicalEvidenceNotFoundError(
                f"Clinical evidence brief '{brief_id}' was not found."
            )
        return ClinicalEvidenceBriefService._to_read(db, brief)

    @staticmethod
    def list_for_visit(
        db: Session,
        visit_id: str,
    ) -> list[ClinicalEvidenceBriefRead]:
        if VisitRepository.get_by_id(db, visit_id) is None:
            raise ClinicalEvidenceNotFoundError(
                f"Visit '{visit_id}' was not found."
            )
        return [
            ClinicalEvidenceBriefService._to_read(db, brief)
            for brief in ClinicalEvidenceBriefRepository.list_by_visit(
                db,
                visit_id,
            )
        ]

    @staticmethod
    def list_audit_logs(
        db: Session,
        brief_id: str,
    ) -> list[AuditLog]:
        ClinicalEvidenceBriefService.get(db, brief_id)
        return AuditLogRepository.list_by_entity(
            db,
            entity_type="clinical_evidence_brief",
            entity_id=brief_id,
        )
