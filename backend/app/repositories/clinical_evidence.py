from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.clinical_evidence import ClinicalEvidenceBrief


class ClinicalEvidenceBriefRepository:
    """Flush-only persistence for immutable evidence-brief snapshots."""

    @staticmethod
    def get_by_id(
        db: Session,
        brief_id: str,
    ) -> ClinicalEvidenceBrief | None:
        return db.get(ClinicalEvidenceBrief, brief_id)

    @staticmethod
    def list_by_visit(
        db: Session,
        visit_id: str,
    ) -> list[ClinicalEvidenceBrief]:
        return list(
            db.scalars(
                select(ClinicalEvidenceBrief)
                .where(ClinicalEvidenceBrief.visit_id == visit_id)
                .order_by(
                    ClinicalEvidenceBrief.created_at.asc(),
                    ClinicalEvidenceBrief.id.asc(),
                )
            ).all()
        )

    @staticmethod
    def create(
        db: Session,
        *,
        brief_id: str,
        visit_id: str,
        intake_id: str,
        report_ids: list[str],
        clinical_context_sha256: str,
        knowledge_fact_ids: list[str],
        knowledge_set_sha256: str,
        knowledge_as_of: date,
        created_by_user_id: str,
        payload: dict,
        sha256: str,
        created_at: datetime,
    ) -> ClinicalEvidenceBrief:
        brief = ClinicalEvidenceBrief(
            id=brief_id,
            visit_id=visit_id,
            intake_id=intake_id,
            report_ids=list(report_ids),
            clinical_context_sha256=clinical_context_sha256,
            knowledge_fact_ids=list(knowledge_fact_ids),
            knowledge_set_sha256=knowledge_set_sha256,
            knowledge_as_of=knowledge_as_of,
            selection_method="clinician_selected",
            output_type="evidence_summary",
            created_by_user_id=created_by_user_id,
            payload=payload,
            sha256=sha256,
            created_at=created_at,
        )
        db.add(brief)
        db.flush()
        db.refresh(brief)
        return brief
