from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.treatment_outcome import TreatmentOutcome


class TreatmentOutcomeRepository:
    """Flush-only persistence for immutable treatment outcomes."""

    @staticmethod
    def get_by_id(
        db: Session,
        outcome_id: str,
    ) -> TreatmentOutcome | None:
        return db.get(TreatmentOutcome, outcome_id)

    @staticmethod
    def list_by_treatment(
        db: Session,
        treatment_id: str,
    ) -> list[TreatmentOutcome]:
        return list(
            db.scalars(
                select(TreatmentOutcome)
                .where(TreatmentOutcome.treatment_id == treatment_id)
                .order_by(
                    TreatmentOutcome.follow_up_day.asc(),
                    TreatmentOutcome.recorded_at.asc(),
                    TreatmentOutcome.id.asc(),
                )
            ).all()
        )

    @staticmethod
    def create(
        db: Session,
        *,
        outcome_id: str,
        treatment_id: str,
        visit_id: str,
        treatment_type: str,
        protocol_code: str | None,
        protocol_version: str | None,
        body_region: str | None,
        clinical_context_sha256: str,
        treatment_snapshot_sha256: str,
        finalization_sha256s: list[str],
        follow_up_day: int,
        outcome_status: str,
        patient_rating: int | None,
        physician_rating: int | None,
        pain_score: int | None,
        function_score: int | None,
        outcome_measures: list[dict],
        adverse_events: list[str],
        notes: str | None,
        created_by_user_id: str,
        payload: dict,
        sha256: str,
        recorded_at: datetime,
    ) -> TreatmentOutcome:
        record = TreatmentOutcome(
            id=outcome_id,
            treatment_id=treatment_id,
            visit_id=visit_id,
            treatment_type=treatment_type,
            protocol_code=protocol_code,
            protocol_version=protocol_version,
            body_region=body_region,
            clinical_context_sha256=clinical_context_sha256,
            treatment_snapshot_sha256=treatment_snapshot_sha256,
            finalization_sha256s=list(finalization_sha256s),
            follow_up_day=follow_up_day,
            outcome_status=outcome_status,
            patient_rating=patient_rating,
            physician_rating=physician_rating,
            pain_score=pain_score,
            function_score=function_score,
            outcome_measures=list(outcome_measures),
            adverse_events=list(adverse_events),
            notes=notes,
            created_by_user_id=created_by_user_id,
            payload=payload,
            sha256=sha256,
            recorded_at=recorded_at,
        )
        db.add(record)
        db.flush()
        db.refresh(record)
        return record
