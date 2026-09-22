"""Append-only, provenance-bound treatment outcome observations."""
from copy import deepcopy
from datetime import datetime, timezone
import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.audit_log import AuditLog
from backend.app.models.session_finalization import SessionFinalization
from backend.app.models.treatment_outcome import TreatmentOutcome
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.treatment_outcome import TreatmentOutcomeRepository
from backend.app.repositories.treatment_session import TreatmentSessionRepository
from backend.app.repositories.visit import VisitRepository
from backend.app.schemas.treatment import TreatmentRead
from backend.app.schemas.treatment_outcome import (
    OutcomeFinalizationReference,
    TreatmentOutcomeCreate,
    TreatmentOutcomePayloadRead,
    TreatmentOutcomeRead,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.clinical_context import (
    ClinicalContextIntegrityError,
    ClinicalContextNotFoundError,
    ClinicalContextService,
)
from backend.app.services.clinical_safety import clinical_context_digest
from backend.app.services.session_finalization import (
    FinalizationIntegrityError,
    FinalizationNotFoundError,
    SessionFinalizationService,
    evidence_digest,
)
from backend.app.services.treatment import (
    TreatmentNotFoundError,
    TreatmentService,
)


CREATE_ROLES = {"physician"}
KNOWN_LIMITATIONS = [
    "This is an observational follow-up record and does not establish that the "
    "treatment caused the observed outcome.",
    "Patient selection, confounding, missing follow-up, concomitant care and "
    "documentation quality can bias comparisons across protocols.",
    "Patient and physician ratings are subjective observations and must not be "
    "treated as interchangeable with validated outcome instruments.",
    "Missing outcomes are not imputed and patients lost to follow-up are not "
    "assumed to have improved or worsened.",
    "This registry does not automatically learn, recommend, rank treatments or "
    "grant clinical clearance.",
]


class TreatmentOutcomeNotFoundError(Exception):
    pass


class TreatmentOutcomeConflictError(Exception):
    pass


class TreatmentOutcomeAuthorizationError(Exception):
    pass


class TreatmentOutcomeIntegrityError(Exception):
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


class TreatmentOutcomeService:
    @staticmethod
    def _require_actor(actor: User | None) -> User:
        if (
            actor is None
            or not actor.is_active
            or actor.role not in CREATE_ROLES
        ):
            raise TreatmentOutcomeAuthorizationError(
                "Only an active physician may record a treatment outcome."
            )
        return actor

    @staticmethod
    def _require_treatment(db: Session, treatment_id: str):
        try:
            return TreatmentService.get_treatment(db, treatment_id)
        except TreatmentNotFoundError as error:
            raise TreatmentOutcomeNotFoundError(str(error)) from error

    @staticmethod
    def _validated_finalizations(
        db: Session,
        treatment_id: str,
    ) -> list[OutcomeFinalizationReference]:
        references: list[OutcomeFinalizationReference] = []
        for session in TreatmentSessionRepository.list_by_treatment(
            db,
            treatment_id,
        ):
            record = db.get(SessionFinalization, session.id)
            if record is None:
                continue
            try:
                finalization = SessionFinalizationService.get(db, session.id)
            except (
                FinalizationIntegrityError,
                FinalizationNotFoundError,
            ) as error:
                raise TreatmentOutcomeIntegrityError(str(error)) from error
            references.append(
                OutcomeFinalizationReference(
                    session_id=session.id,
                    session_number=session.session_number,
                    finalization_sha256=finalization.sha256,
                )
            )
        if not references:
            raise TreatmentOutcomeConflictError(
                "At least one immutable completed-session finalization is "
                "required before recording a treatment outcome."
            )
        references.sort(key=lambda item: (item.session_number, item.session_id))
        return references

    @staticmethod
    def _validate(
        db: Session,
        record: TreatmentOutcome,
    ) -> TreatmentOutcomePayloadRead:
        try:
            raw = deepcopy(record.payload)
            payload = TreatmentOutcomePayloadRead.model_validate(raw)
            valid = (
                isinstance(raw, dict)
                and evidence_digest(raw) == record.sha256
                and payload.id == record.id
                and payload.treatment_id == record.treatment_id
                and payload.visit_id == record.visit_id
                and payload.treatment_type == record.treatment_type
                and payload.protocol_code == record.protocol_code
                and payload.protocol_version == record.protocol_version
                and payload.body_region == record.body_region
                and payload.clinical_context_sha256
                == record.clinical_context_sha256
                and payload.treatment_snapshot_sha256
                == record.treatment_snapshot_sha256
                == evidence_digest(payload.treatment_snapshot)
                and [
                    item.finalization_sha256
                    for item in payload.finalizations
                ] == list(record.finalization_sha256s)
                and payload.follow_up_day == record.follow_up_day
                and payload.outcome_status == record.outcome_status
                and payload.patient_rating == record.patient_rating
                and payload.physician_rating == record.physician_rating
                and payload.pain_score == record.pain_score
                and payload.function_score == record.function_score
                and [
                    item.model_dump(mode="json")
                    for item in payload.outcome_measures
                ] == list(record.outcome_measures)
                and payload.adverse_events == list(record.adverse_events)
                and payload.notes == record.notes
                and payload.created_by_user_id == record.created_by_user_id
                and payload.known_limitations == KNOWN_LIMITATIONS
                and _same_timestamp(payload.recorded_at, record.recorded_at)
            )
            sessions = {
                item.id: item
                for item in TreatmentSessionRepository.list_by_treatment(
                    db,
                    record.treatment_id,
                )
            }
            if len(payload.finalizations) != len(
                {item.session_id for item in payload.finalizations}
            ):
                valid = False
            for reference in payload.finalizations:
                session = sessions.get(reference.session_id)
                if (
                    session is None
                    or session.session_number != reference.session_number
                ):
                    valid = False
                    break
                finalization = SessionFinalizationService.get(
                    db,
                    reference.session_id,
                )
                if finalization.sha256 != reference.finalization_sha256:
                    valid = False
                    break
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            ValidationError,
            FinalizationIntegrityError,
            FinalizationNotFoundError,
        ):
            valid = False
            payload = None
        if not valid or payload is None:
            raise TreatmentOutcomeIntegrityError(
                "Stored treatment outcome failed its integrity check."
            )
        return payload

    @staticmethod
    def _to_read(
        db: Session,
        record: TreatmentOutcome,
    ) -> TreatmentOutcomeRead:
        payload = TreatmentOutcomeService._validate(db, record)
        return TreatmentOutcomeRead(
            id=record.id,
            treatment_id=record.treatment_id,
            visit_id=record.visit_id,
            treatment_type=record.treatment_type,
            protocol_code=record.protocol_code,
            protocol_version=record.protocol_version,
            body_region=record.body_region,
            clinical_context_sha256=record.clinical_context_sha256,
            treatment_snapshot_sha256=record.treatment_snapshot_sha256,
            finalization_sha256s=list(record.finalization_sha256s),
            follow_up_day=record.follow_up_day,
            outcome_status=record.outcome_status,
            patient_rating=record.patient_rating,
            physician_rating=record.physician_rating,
            pain_score=record.pain_score,
            function_score=record.function_score,
            outcome_measures=payload.outcome_measures,
            adverse_events=list(record.adverse_events),
            notes=record.notes,
            created_by_user_id=record.created_by_user_id,
            sha256=record.sha256,
            recorded_at=record.recorded_at,
            payload=payload,
        )

    @staticmethod
    @clinical_record_write
    def create(
        db: Session,
        treatment_id: str,
        payload: TreatmentOutcomeCreate,
        *,
        actor: User | None,
    ) -> TreatmentOutcomeRead:
        actor = TreatmentOutcomeService._require_actor(actor)
        treatment = TreatmentOutcomeService._require_treatment(
            db,
            treatment_id,
        )
        try:
            context = ClinicalContextService.get_current_context(
                db,
                treatment.visit_id,
            )
        except ClinicalContextNotFoundError as error:
            raise TreatmentOutcomeNotFoundError(str(error)) from error
        except ClinicalContextIntegrityError as error:
            raise TreatmentOutcomeIntegrityError(str(error)) from error
        if context.intake is None:
            raise TreatmentOutcomeConflictError(
                "A final structured clinical intake is required before "
                "recording outcome data for future cohort analysis."
            )
        context_hash = clinical_context_digest(context)
        if payload.expected_clinical_context_sha256 != context_hash:
            raise TreatmentOutcomeConflictError(
                "The clinical context changed; reload it before recording "
                "the follow-up outcome."
            )

        finalizations = TreatmentOutcomeService._validated_finalizations(
            db,
            treatment_id,
        )
        treatment_snapshot = TreatmentRead.model_validate(
            treatment
        ).model_dump(mode="json")
        treatment_snapshot_sha256 = evidence_digest(treatment_snapshot)
        protocol_snapshot = treatment.protocol_snapshot or {}
        protocol_code = protocol_snapshot.get("code")
        protocol_version = treatment.protocol_version

        outcome_id = str(uuid.uuid4())
        recorded_at = datetime.now(timezone.utc)
        stored_payload = TreatmentOutcomePayloadRead(
            schema_version=1,
            id=outcome_id,
            treatment_id=treatment.id,
            visit_id=treatment.visit_id,
            treatment_type=treatment.treatment_type,
            protocol_code=protocol_code,
            protocol_version=protocol_version,
            body_region=treatment.body_region,
            clinical_context_sha256=context_hash,
            treatment_snapshot_sha256=treatment_snapshot_sha256,
            treatment_snapshot=treatment_snapshot,
            finalizations=finalizations,
            follow_up_day=payload.follow_up_day,
            outcome_status=payload.outcome_status,
            patient_rating=payload.patient_rating,
            patient_rating_source=(
                "clinician_documented_patient_report"
                if payload.patient_rating is not None
                else None
            ),
            physician_rating=payload.physician_rating,
            pain_score=payload.pain_score,
            function_score=payload.function_score,
            outcome_measures=payload.outcome_measures,
            adverse_events=list(payload.adverse_events),
            notes=payload.notes,
            created_by_user_id=actor.id,
            recorded_at=recorded_at.isoformat(),
            known_limitations=list(KNOWN_LIMITATIONS),
        ).model_dump(mode="json")
        sha256 = evidence_digest(stored_payload)

        record = TreatmentOutcomeRepository.create(
            db,
            outcome_id=outcome_id,
            treatment_id=treatment.id,
            visit_id=treatment.visit_id,
            treatment_type=treatment.treatment_type,
            protocol_code=protocol_code,
            protocol_version=protocol_version,
            body_region=treatment.body_region,
            clinical_context_sha256=context_hash,
            treatment_snapshot_sha256=treatment_snapshot_sha256,
            finalization_sha256s=[
                item.finalization_sha256 for item in finalizations
            ],
            follow_up_day=payload.follow_up_day,
            outcome_status=payload.outcome_status,
            patient_rating=payload.patient_rating,
            physician_rating=payload.physician_rating,
            pain_score=payload.pain_score,
            function_score=payload.function_score,
            outcome_measures=[
                item.model_dump(mode="json")
                for item in payload.outcome_measures
            ],
            adverse_events=list(payload.adverse_events),
            notes=payload.notes,
            created_by_user_id=actor.id,
            payload=stored_payload,
            sha256=sha256,
            recorded_at=recorded_at,
        )
        AuditLogRepository.create(
            db,
            commit=False,
            entity_type="treatment_outcome",
            entity_id=record.id,
            event_type="treatment_outcome_recorded",
            from_state=None,
            to_state="immutable",
            message=(
                "An append-only treatment follow-up outcome was recorded "
                "for future independently reviewed aggregate analysis."
            ),
            event_data={
                "treatment_id": treatment.id,
                "visit_id": treatment.visit_id,
                "treatment_type": treatment.treatment_type,
                "protocol_code": protocol_code,
                "protocol_version": protocol_version,
                "follow_up_day": payload.follow_up_day,
                "outcome_status": payload.outcome_status,
                "clinical_context_sha256": context_hash,
                "treatment_snapshot_sha256": treatment_snapshot_sha256,
                "finalization_count": len(finalizations),
                "outcome_sha256": sha256,
                "is_causal_evidence": False,
                "is_treatment_recommendation": False,
                "requires_bias_review": True,
            },
            **actor_data(actor),
        )
        return TreatmentOutcomeService._to_read(db, record)

    @staticmethod
    def get(
        db: Session,
        outcome_id: str,
    ) -> TreatmentOutcomeRead:
        record = TreatmentOutcomeRepository.get_by_id(db, outcome_id)
        if record is None:
            raise TreatmentOutcomeNotFoundError(
                f"Treatment outcome '{outcome_id}' was not found."
            )
        return TreatmentOutcomeService._to_read(db, record)

    @staticmethod
    def list_for_treatment(
        db: Session,
        treatment_id: str,
    ) -> list[TreatmentOutcomeRead]:
        TreatmentOutcomeService._require_treatment(db, treatment_id)
        return [
            TreatmentOutcomeService._to_read(db, record)
            for record in TreatmentOutcomeRepository.list_by_treatment(
                db,
                treatment_id,
            )
        ]

    @staticmethod
    def list_for_visit(
        db: Session,
        visit_id: str,
    ) -> list[TreatmentOutcomeRead]:
        if VisitRepository.get_by_id(db, visit_id) is None:
            raise TreatmentOutcomeNotFoundError(
                f"Visit '{visit_id}' was not found."
            )
        return [
            TreatmentOutcomeService._to_read(db, record)
            for record in TreatmentOutcomeRepository.list_by_visit(
                db,
                visit_id,
            )
        ]

    @staticmethod
    def list_audit_logs(
        db: Session,
        outcome_id: str,
    ) -> list[AuditLog]:
        TreatmentOutcomeService.get(db, outcome_id)
        return AuditLogRepository.list_by_entity(
            db,
            entity_type="treatment_outcome",
            entity_id=outcome_id,
        )
