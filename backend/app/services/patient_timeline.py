from datetime import datetime, timezone

from sqlalchemy import (
    and_,
    or_,
    select,
)
from sqlalchemy.orm import Session

from backend.app.models.audit_log import AuditLog
from backend.app.models.patient import Patient
from backend.app.models.treatment import Treatment
from backend.app.models.treatment_session import (
    TreatmentSession,
)
from backend.app.models.visit import Visit
from backend.app.schemas.patient_timeline import (
    PatientTimelineItem,
    PatientTimelineResponse,
)


class PatientTimelineNotFoundError(Exception):
    pass


class PatientTimelineService:
    @staticmethod
    def _normalize_timestamp(
        value: datetime,
    ) -> datetime:
        if value.tzinfo is None:
            return value.replace(
                tzinfo=timezone.utc
            )

        return value.astimezone(
            timezone.utc
        )

    @staticmethod
    def _visit_items(
        visits: list[Visit],
    ) -> list[PatientTimelineItem]:
        items = []

        for visit in visits:
            items.append(
                PatientTimelineItem(
                    id=f"visit:{visit.id}",
                    timestamp=(
                        PatientTimelineService
                        ._normalize_timestamp(
                            visit.visit_date
                        )
                    ),
                    item_type="visit",
                    entity_type="visit",
                    entity_id=visit.id,
                    event_type="visit",
                    title="Clinical visit",
                    status=visit.status,
                    details={
                        "body_region": (
                            visit.body_region
                        ),
                    },
                )
            )

        return items

    @staticmethod
    def _treatment_items(
        treatments: list[Treatment],
    ) -> list[PatientTimelineItem]:
        items = []

        for treatment in treatments:
            event_time = (
                treatment.performed_at
                or treatment.created_at
            )

            items.append(
                PatientTimelineItem(
                    id=(
                        f"treatment:"
                        f"{treatment.id}"
                    ),
                    timestamp=(
                        PatientTimelineService
                        ._normalize_timestamp(
                            event_time
                        )
                    ),
                    item_type="treatment",
                    entity_type="treatment",
                    entity_id=treatment.id,
                    event_type="treatment",
                    title=(
                        f"{treatment.treatment_type} "
                        "treatment"
                    ),
                    status=treatment.status,
                    details={
                        "visit_id": (
                            treatment.visit_id
                        ),
                        "treatment_type": (
                            treatment.treatment_type
                        ),
                        "body_region": (
                            treatment.body_region
                        ),
                        "protocol_name": (
                            treatment.protocol_name
                        ),
                        "protocol_version": (
                            treatment.protocol_version
                        ),
                    },
                )
            )

        return items

    @staticmethod
    def _session_items(
        sessions: list[TreatmentSession],
    ) -> list[PatientTimelineItem]:
        items = []

        for session in sessions:
            event_time = (
                session.completed_at
                or session.started_at
                or session.scheduled_at
                or session.created_at
            )

            items.append(
                PatientTimelineItem(
                    id=(
                        "session:"
                        f"{session.id}"
                    ),
                    timestamp=(
                        PatientTimelineService
                        ._normalize_timestamp(
                            event_time
                        )
                    ),
                    item_type="session",
                    entity_type=(
                        "treatment_session"
                    ),
                    entity_id=session.id,
                    event_type=(
                        "treatment_session"
                    ),
                    title=(
                        "Treatment session "
                        f"{session.session_number}"
                    ),
                    status=session.status,
                    details={
                        "treatment_id": (
                            session.treatment_id
                        ),
                        "session_number": (
                            session.session_number
                        ),
                        "body_region": (
                            session.body_region
                        ),
                        "dose_or_volume": (
                            session.dose_or_volume
                        ),
                    },
                )
            )

        return items

    @staticmethod
    def _audit_items(
        audit_logs: list[AuditLog],
    ) -> list[PatientTimelineItem]:
        items = []

        for log in audit_logs:
            items.append(
                PatientTimelineItem(
                    id=f"audit:{log.id}",
                    timestamp=(
                        PatientTimelineService
                        ._normalize_timestamp(
                            log.created_at
                        )
                    ),
                    item_type="audit",
                    entity_type=(
                        log.entity_type
                    ),
                    entity_id=log.entity_id,
                    event_type=log.event_type,
                    title=(
                        log.message
                        or log.event_type
                    ),
                    status=(
                        log.to_state
                        or log.from_state
                    ),
                    actor_user_id=(
                        log.actor_user_id
                    ),
                    actor_username=(
                        log.actor_username
                    ),
                    actor_display_name=(
                        log.actor_display_name
                    ),
                    actor_role=(
                        log.actor_role
                    ),
                    details=log.event_data,
                )
            )

        return items

    @staticmethod
    def get_patient_timeline(
        db: Session,
        patient_id: str,
    ) -> PatientTimelineResponse:
        patient = db.get(
            Patient,
            patient_id,
        )

        if patient is None:
            raise PatientTimelineNotFoundError(
                f"Patient '{patient_id}' "
                "was not found."
            )

        visit_statement = (
            select(Visit)
            .where(
                Visit.patient_id
                == patient_id
            )
        )

        visits = list(
            db.scalars(
                visit_statement
            ).all()
        )

        visit_ids = [
            visit.id
            for visit in visits
        ]

        treatments: list[Treatment] = []

        if visit_ids:
            treatment_statement = (
                select(Treatment)
                .where(
                    Treatment.visit_id.in_(
                        visit_ids
                    )
                )
            )

            treatments = list(
                db.scalars(
                    treatment_statement
                ).all()
            )

        treatment_ids = [
            treatment.id
            for treatment in treatments
        ]

        sessions: list[
            TreatmentSession
        ] = []

        if treatment_ids:
            session_statement = (
                select(TreatmentSession)
                .where(
                    TreatmentSession
                    .treatment_id.in_(
                        treatment_ids
                    )
                )
            )

            sessions = list(
                db.scalars(
                    session_statement
                ).all()
            )

        session_ids = [
            session.id
            for session in sessions
        ]

        audit_conditions = [
            and_(
                AuditLog.entity_type
                == "patient",
                AuditLog.entity_id
                == patient_id,
            )
        ]

        if visit_ids:
            audit_conditions.append(
                and_(
                    AuditLog.entity_type
                    == "visit",
                    AuditLog.entity_id.in_(
                        visit_ids
                    ),
                )
            )

        if treatment_ids:
            audit_conditions.append(
                and_(
                    AuditLog.entity_type
                    == "treatment",
                    AuditLog.entity_id.in_(
                        treatment_ids
                    ),
                )
            )

        if session_ids:
            audit_conditions.append(
                and_(
                    AuditLog.entity_type
                    == "treatment_session",
                    AuditLog.entity_id.in_(
                        session_ids
                    ),
                )
            )

        audit_statement = (
            select(AuditLog)
            .where(
                or_(
                    *audit_conditions
                )
            )
        )

        audit_logs = list(
            db.scalars(
                audit_statement
            ).all()
        )

        items = []

        items.extend(
            PatientTimelineService
            ._visit_items(
                visits
            )
        )

        items.extend(
            PatientTimelineService
            ._treatment_items(
                treatments
            )
        )

        items.extend(
            PatientTimelineService
            ._session_items(
                sessions
            )
        )

        items.extend(
            PatientTimelineService
            ._audit_items(
                audit_logs
            )
        )

        items.sort(
            key=lambda item: (
                item.timestamp,
                item.id,
            )
        )

        return PatientTimelineResponse(
            patient_id=patient_id,
            count=len(items),
            items=items,
        )