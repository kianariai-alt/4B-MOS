from collections import Counter
from datetime import (
    datetime,
    time,
    timedelta,
    timezone,
)
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import (
    settings,
)
from backend.app.models.audit_log import (
    AuditLog,
)
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
from backend.app.schemas.operations_dashboard import (
    DashboardOperationalFlag,
    OperationsDashboardResponse,
)


class OperationsDashboardService:
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
    def get_dashboard(
        db: Session,
    ) -> OperationsDashboardResponse:
        clinic_timezone = ZoneInfo(
            settings.CLINIC_TIMEZONE
        )

        now_utc = datetime.now(
            timezone.utc
        )

        now_local = now_utc.astimezone(
            clinic_timezone
        )

        local_day_start = datetime.combine(
            now_local.date(),
            time.min,
            tzinfo=clinic_timezone,
        )

        local_day_end = (
            local_day_start
            + timedelta(days=1)
        )

        day_start_utc = (
            local_day_start.astimezone(
                timezone.utc
            )
        )

        day_end_utc = (
            local_day_end.astimezone(
                timezone.utc
            )
        )

        patients = list(
            db.scalars(
                select(Patient)
            ).all()
        )

        visits = list(
            db.scalars(
                select(Visit)
            ).all()
        )

        treatments = list(
            db.scalars(
                select(Treatment)
            ).all()
        )

        sessions = list(
            db.scalars(
                select(TreatmentSession)
            ).all()
        )

        last_24h = (
            now_utc
            - timedelta(hours=24)
        )

        audit_logs = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.created_at
                    >= last_24h
                )
            ).all()
        )

        active_patients = [
            patient
            for patient in patients
            if patient.is_active
        ]

        inactive_patients = [
            patient
            for patient in patients
            if not patient.is_active
        ]

        open_visits = [
            visit
            for visit in visits
            if visit.status == "open"
        ]

        active_treatments = [
            treatment
            for treatment in treatments
            if treatment.status
            in {
                "planned",
                "in_progress",
            }
        ]

        completed_treatments = [
            treatment
            for treatment in treatments
            if treatment.status
            == "completed"
        ]

        treatment_type_counts = dict(
            Counter(
                treatment.treatment_type
                for treatment in treatments
            )
        )

        treatment_status_counts = dict(
            Counter(
                treatment.status
                for treatment in treatments
            )
        )

        session_status_counts = dict(
            Counter(
                session.status
                for session in sessions
            )
        )

        scheduled_today = []

        upcoming_planned = []

        overdue_planned = []

        adverse_event_sessions = []

        for session in sessions:
            scheduled_at = (
                session.scheduled_at
            )

            if (
                scheduled_at is not None
            ):
                scheduled_utc = (
                    OperationsDashboardService
                    ._as_utc(
                        scheduled_at
                    )
                )

                if (
                    day_start_utc
                    <= scheduled_utc
                    < day_end_utc
                ):
                    scheduled_today.append(
                        session
                    )

                if (
                    session.status
                    == "planned"
                ):
                    if scheduled_utc >= now_utc:
                        upcoming_planned.append(
                            session
                        )
                    else:
                        overdue_planned.append(
                            session
                        )

            if (
                session.adverse_events
                is not None
                and session.adverse_events
                .strip()
            ):
                adverse_event_sessions.append(
                    session
                )

        audit_event_type_counts = dict(
            Counter(
                log.event_type
                for log in audit_logs
            )
        )

        operational_flags = []

        if overdue_planned:
            operational_flags.append(
                DashboardOperationalFlag(
                    code=(
                        "overdue_planned_sessions"
                    ),
                    severity="attention",
                    message=(
                        "One or more planned "
                        "sessions are overdue."
                    ),
                    count=len(
                        overdue_planned
                    ),
                )
            )

        if adverse_event_sessions:
            operational_flags.append(
                DashboardOperationalFlag(
                    code=(
                        "documented_adverse_events"
                    ),
                    severity="attention",
                    message=(
                        "Sessions with "
                        "documented adverse "
                        "events exist."
                    ),
                    count=len(
                        adverse_event_sessions
                    ),
                )
            )

        if open_visits:
            operational_flags.append(
                DashboardOperationalFlag(
                    code="open_visits",
                    severity="info",
                    message=(
                        "There are currently "
                        "open clinical visits."
                    ),
                    count=len(
                        open_visits
                    ),
                )
            )

        return OperationsDashboardResponse(
            generated_at=now_utc,
            clinic_timezone=(
                settings.CLINIC_TIMEZONE
            ),
            total_patients=len(
                patients
            ),
            active_patient_count=len(
                active_patients
            ),
            inactive_patient_count=len(
                inactive_patients
            ),
            total_visits=len(
                visits
            ),
            open_visit_count=len(
                open_visits
            ),
            total_treatments=len(
                treatments
            ),
            active_treatment_count=len(
                active_treatments
            ),
            completed_treatment_count=len(
                completed_treatments
            ),
            treatment_type_counts=(
                treatment_type_counts
            ),
            treatment_status_counts=(
                treatment_status_counts
            ),
            total_sessions=len(
                sessions
            ),
            session_status_counts=(
                session_status_counts
            ),
            sessions_scheduled_today=len(
                scheduled_today
            ),
            upcoming_planned_sessions=len(
                upcoming_planned
            ),
            overdue_planned_sessions=len(
                overdue_planned
            ),
            sessions_with_adverse_events=len(
                adverse_event_sessions
            ),
            audit_events_last_24h=len(
                audit_logs
            ),
            audit_event_type_counts=(
                audit_event_type_counts
            ),
            operational_flags=(
                operational_flags
            ),
        )