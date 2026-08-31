from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.patient import (
    Patient,
)
from backend.app.models.treatment import (
    Treatment,
)
from backend.app.models.treatment_session import (
    TreatmentSession,
)
from backend.app.models.visit import Visit
from backend.app.schemas.patient_summary import (
    ActiveTreatmentSummary,
    LatestVisitSummary,
    OperationalFlag,
    PatientClinicalSummaryResponse,
    PatientIdentitySummary,
    SessionSummary,
)


class PatientSummaryNotFoundError(
    Exception
):
    pass


class PatientSummaryService:
    @staticmethod
    def _as_utc(
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
    def _session_summary(
        session: TreatmentSession,
        treatment_map: dict[
            str,
            Treatment,
        ],
    ) -> SessionSummary:
        treatment = treatment_map[
            session.treatment_id
        ]

        return SessionSummary(
            id=session.id,
            treatment_id=(
                session.treatment_id
            ),
            treatment_type=(
                treatment.treatment_type
            ),
            session_number=(
                session.session_number
            ),
            status=session.status,
            scheduled_at=(
                session.scheduled_at
            ),
            started_at=(
                session.started_at
            ),
            completed_at=(
                session.completed_at
            ),
            body_region=(
                session.body_region
            ),
        )

    @staticmethod
    def get_summary(
        db: Session,
        patient_id: str,
    ) -> PatientClinicalSummaryResponse:
        patient = db.get(
            Patient,
            patient_id,
        )

        if patient is None:
            raise PatientSummaryNotFoundError(
                f"Patient '{patient_id}' "
                "was not found."
            )

        visit_statement = (
            select(Visit)
            .where(
                Visit.patient_id
                == patient_id
            )
            .order_by(
                Visit.visit_date.desc()
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

        treatments: list[
            Treatment
        ] = []

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

        treatment_map = {
            treatment.id: treatment
            for treatment in treatments
        }

        treatment_status_counts = dict(
            Counter(
                treatment.status
                for treatment in treatments
            )
        )

        treatment_type_counts = dict(
            Counter(
                treatment.treatment_type
                for treatment in treatments
            )
        )

        active_treatment_models = [
            treatment
            for treatment in treatments
            if treatment.status
            in {
                "planned",
                "in_progress",
            }
        ]

        active_treatment_models.sort(
            key=lambda treatment: (
                PatientSummaryService
                ._as_utc(
                    treatment.created_at
                )
            ),
            reverse=True,
        )

        active_treatments = [
            ActiveTreatmentSummary(
                id=treatment.id,
                treatment_type=(
                    treatment.treatment_type
                ),
                status=treatment.status,
                body_region=(
                    treatment.body_region
                ),
                protocol_name=(
                    treatment.protocol_name
                ),
                protocol_version=(
                    treatment.protocol_version
                ),
                created_at=(
                    treatment.created_at
                ),
            )
            for treatment
            in active_treatment_models
        ]

        now = datetime.now(
            timezone.utc
        )

        future_sessions = [
            session
            for session in sessions
            if (
                session.status
                == "planned"
                and session.scheduled_at
                is not None
                and PatientSummaryService
                ._as_utc(
                    session.scheduled_at
                )
                >= now
            )
        ]

        future_sessions.sort(
            key=lambda session: (
                PatientSummaryService
                ._as_utc(
                    session.scheduled_at
                )
            )
        )

        next_scheduled_session = None

        if future_sessions:
            next_scheduled_session = (
                PatientSummaryService
                ._session_summary(
                    future_sessions[0],
                    treatment_map,
                )
            )

        overdue_sessions = [
            session
            for session in sessions
            if (
                session.status
                == "planned"
                and session.scheduled_at
                is not None
                and PatientSummaryService
                ._as_utc(
                    session.scheduled_at
                )
                < now
            )
        ]

        completed_sessions = [
            session
            for session in sessions
            if session.status
            == "completed"
        ]

        def completed_time(
            session: TreatmentSession,
        ) -> datetime:
            event_time = (
                session.completed_at
                or session.updated_at
                or session.created_at
            )

            return (
                PatientSummaryService
                ._as_utc(
                    event_time
                )
            )

        completed_sessions.sort(
            key=completed_time,
            reverse=True,
        )

        last_completed_session = None

        if completed_sessions:
            last_completed_session = (
                PatientSummaryService
                ._session_summary(
                    completed_sessions[0],
                    treatment_map,
                )
            )

        adverse_event_sessions = [
            session
            for session in sessions
            if (
                session.adverse_events
                is not None
                and session.adverse_events
                .strip()
            )
        ]

        latest_visit = None

        if visits:
            visit = visits[0]

            latest_visit = (
                LatestVisitSummary(
                    id=visit.id,
                    visit_date=(
                        visit.visit_date
                    ),
                    status=visit.status,
                    body_region=(
                        visit.body_region
                    ),
                )
            )

        operational_flags = []

        if not patient.is_active:
            operational_flags.append(
                OperationalFlag(
                    code=(
                        "patient_inactive"
                    ),
                    severity="info",
                    message=(
                        "Patient record is "
                        "inactive."
                    ),
                )
            )

        if overdue_sessions:
            operational_flags.append(
                OperationalFlag(
                    code=(
                        "overdue_planned_sessions"
                    ),
                    severity="attention",
                    message=(
                        "One or more planned "
                        "sessions are past "
                        "their scheduled time."
                    ),
                    count=len(
                        overdue_sessions
                    ),
                )
            )

        if adverse_event_sessions:
            operational_flags.append(
                OperationalFlag(
                    code=(
                        "documented_"
                        "adverse_events"
                    ),
                    severity="attention",
                    message=(
                        "One or more sessions "
                        "contain a documented "
                        "adverse event."
                    ),
                    count=len(
                        adverse_event_sessions
                    ),
                )
            )

        return (
            PatientClinicalSummaryResponse(
                patient=(
                    PatientIdentitySummary(
                        id=patient.id,
                        patient_code=(
                            patient.patient_code
                        ),
                        first_name=(
                            patient.first_name
                        ),
                        last_name=(
                            patient.last_name
                        ),
                        date_of_birth=(
                            patient.date_of_birth
                        ),
                        is_active=(
                            patient.is_active
                        ),
                    )
                ),
                total_visits=len(
                    visits
                ),
                open_visit_count=sum(
                    1
                    for visit in visits
                    if visit.status == "open"
                ),
                total_treatments=len(
                    treatments
                ),
                active_treatment_count=len(
                    active_treatment_models
                ),
                completed_treatment_count=sum(
                    1
                    for treatment
                    in treatments
                    if treatment.status
                    == "completed"
                ),
                total_sessions=len(
                    sessions
                ),
                completed_session_count=len(
                    completed_sessions
                ),
                overdue_planned_session_count=(
                    len(overdue_sessions)
                ),
                sessions_with_adverse_events=(
                    len(
                        adverse_event_sessions
                    )
                ),
                treatment_status_counts=(
                    treatment_status_counts
                ),
                treatment_type_counts=(
                    treatment_type_counts
                ),
                latest_visit=latest_visit,
                active_treatments=(
                    active_treatments
                ),
                next_scheduled_session=(
                    next_scheduled_session
                ),
                last_completed_session=(
                    last_completed_session
                ),
                operational_flags=(
                    operational_flags
                ),
            )
        )