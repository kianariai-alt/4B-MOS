from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.treatment import Treatment
from backend.app.models.treatment_decision import TreatmentDecision
from backend.app.models.treatment_outcome import TreatmentOutcome


class TreatmentDecisionRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        decision_id: str,
    ) -> TreatmentDecision | None:
        return db.get(TreatmentDecision, decision_id)

    @staticmethod
    def list_by_visit(
        db: Session,
        visit_id: str,
    ) -> list[TreatmentDecision]:
        return list(
            db.scalars(
                select(TreatmentDecision)
                .where(TreatmentDecision.visit_id == visit_id)
                .order_by(
                    TreatmentDecision.decided_at.asc(),
                    TreatmentDecision.id.asc(),
                )
            ).all()
        )

    @staticmethod
    def latest_by_visit(
        db: Session,
        visit_id: str,
    ) -> TreatmentDecision | None:
        return db.scalar(
            select(TreatmentDecision)
            .where(TreatmentDecision.visit_id == visit_id)
            .order_by(
                TreatmentDecision.decided_at.desc(),
                TreatmentDecision.id.desc(),
            )
            .limit(1)
        )

    @staticmethod
    def linked_treatment_ids(
        db: Session,
        decision_id: str,
    ) -> list[str]:
        return list(
            db.scalars(
                select(Treatment.id)
                .where(
                    Treatment.source_treatment_decision_id == decision_id
                )
                .order_by(Treatment.created_at.asc(), Treatment.id.asc())
            ).all()
        )

    @staticmethod
    def linked_outcome_ids(
        db: Session,
        decision_id: str,
    ) -> list[str]:
        return list(
            db.scalars(
                select(TreatmentOutcome.id)
                .join(
                    Treatment,
                    TreatmentOutcome.treatment_id == Treatment.id,
                )
                .where(
                    Treatment.source_treatment_decision_id == decision_id
                )
                .order_by(
                    TreatmentOutcome.recorded_at.asc(),
                    TreatmentOutcome.id.asc(),
                )
            ).all()
        )

    @staticmethod
    def create(
        db: Session,
        *,
        decision_id: str,
        visit_id: str,
        supersedes_decision_id: str | None,
        decision_type: str,
        clinical_context_sha256: str,
        roadmap_sha256: str,
        selected_protocols: list[dict],
        rationale: str,
        modification_summary: str | None,
        patient_preference_summary: str | None,
        evidence_brief_ids: list[str],
        decided_by_user_id: str,
        payload: dict,
        sha256: str,
        decided_at,
    ) -> TreatmentDecision:
        record = TreatmentDecision(
            id=decision_id,
            visit_id=visit_id,
            supersedes_decision_id=supersedes_decision_id,
            decision_type=decision_type,
            clinical_context_sha256=clinical_context_sha256,
            roadmap_sha256=roadmap_sha256,
            selected_protocols=list(selected_protocols),
            rationale=rationale,
            modification_summary=modification_summary,
            patient_preference_summary=patient_preference_summary,
            evidence_brief_ids=list(evidence_brief_ids),
            decided_by_user_id=decided_by_user_id,
            payload=payload,
            sha256=sha256,
            decided_at=decided_at,
        )
        db.add(record)
        db.flush()
        db.refresh(record)
        return record
