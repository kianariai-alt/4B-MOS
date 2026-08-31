from datetime import (
    datetime,
    time,
    timedelta,
    timezone,
)
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.patient import Patient
from backend.app.models.treatment import Treatment
from backend.app.models.treatment_session import (
    TreatmentSession,
)
from backend.app.models.visit import Visit
from backend.app.schemas.session_worklist import (
    SessionWorklistItem,
    SessionWorklistResponse,
)


class SessionWorklistService:
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
    def _make_item(
        *,
        session: TreatmentSession,
        treatment: Treatment,
        visit: Visit,
        patient: Patient,
        now_utc: datetime,
    ) -> SessionWorklistItem:
        scheduled_at = (
            session.scheduled_at
        )

        is_overdue = False

        if (
            session.status == "planned"
            and scheduled_at is not None
        ):
            is_overdue = (
                SessionWorklistService
                ._as_utc(
                    scheduled_at
                )
                < now_utc
            )

        has_adverse_event = (
            session.adverse_events
            is not None
            and bool(
                session.adverse_events.strip()
            )
        )

        return SessionWorklistItem(
            session_id=session.id,
            treatment_id=treatment.id,
            visit_id=visit.id,
            patient_id=patient.id,
            patient_code=(
                patient.patient_code
            ),
            patient_name=(
                f"{patient.first_name} "
                f"{patient.last_name}"
            ),
            treatment_type=(
                treatment.treatment_type
            ),
            session_number=(
                session.session_number
            ),
            status=session.status,
            scheduled_at=scheduled_at,
            body_region=(
                session.body_region
                or treatment.body_region
            ),
            dose_or_volume=(
                session.dose_or_volume
            ),
            is_overdue=is_overdue,
            has_documented_adverse_event=(
                has_adverse_event
            ),
        )

    @staticmethod
    def get_worklist(
        db: Session,
        *,
        days: int = 7,
    ) -> SessionWorklistResponse:
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

        horizon_end_local = (
            local_day_end
            + timedelta(days=days)
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

        horizon_end_utc = (
            horizon_end_local.astimezone(
                timezone.utc
            )
        )

        statement = (
            select(
                TreatmentSession,
                Treatment,
                Visit,
                Patient,
            )
            .join(
                Treatment,
                TreatmentSession.treatment_id
                == Treatment.id,
            )
            .join(
                Visit,
                Treatment.visit_id
                == Visit.id,
            )
            .join(
                Patient,
                Visit.patient_id
                == Patient.id,
            )
        )

        rows = db.execute(
            statement
        ).all()

        today = []
        overdue = []
        upcoming = []
        unscheduled = []

        for (
            session,
            treatment,
            visit,
            patient,
        ) in rows:
            item = (
                SessionWorklistService
                ._make_item(
                    session=session,
                    treatment=treatment,
                    visit=visit,
                    patient=patient,
                    now_utc=now_utc,
                )
            )

            scheduled_at = (
                session.scheduled_at
            )

            if scheduled_at is None:
                if session.status == "planned":
                    unscheduled.append(
                        item
                    )

                continue

            scheduled_utc = (
                SessionWorklistService
                ._as_utc(
                    scheduled_at
                )
            )

            if (
                day_start_utc
                <= scheduled_utc
                < day_end_utc
            ):
                today.append(
                    item
                )

                continue

            if (
                session.status == "planned"
                and scheduled_utc
                < day_start_utc
            ):
                overdue.append(
                    item
                )

                continue

            if (
                session.status == "planned"
                and day_end_utc
                <= scheduled_utc
                < horizon_end_utc
            ):
                upcoming.append(
                    item
                )

        def scheduled_sort_key(
            item: SessionWorklistItem,
        ) -> datetime:
            if item.scheduled_at is None:
                return datetime.max.replace(
                    tzinfo=timezone.utc
                )

            return (
                SessionWorklistService
                ._as_utc(
                    item.scheduled_at
                )
            )

        today.sort(
            key=scheduled_sort_key
        )

        overdue.sort(
            key=scheduled_sort_key
        )

        upcoming.sort(
            key=scheduled_sort_key
        )

        unscheduled.sort(
            key=lambda item: (
                item.patient_code,
                item.treatment_type,
                item.session_number,
            )
        )

        today_overdue_count = sum(
            1
            for item in today
            if item.is_overdue
        )

        return SessionWorklistResponse(
            generated_at=now_utc,
            clinic_timezone=(
                settings.CLINIC_TIMEZONE
            ),
            local_date=(
                now_local.date()
            ),
            horizon_days=days,
            today_count=len(today),
            today_overdue_count=(
                today_overdue_count
            ),
            overdue_count=len(
                overdue
            ),
            upcoming_count=len(
                upcoming
            ),
            unscheduled_count=len(
                unscheduled
            ),
            today=today,
            overdue=overdue,
            upcoming=upcoming,
            unscheduled=unscheduled,
        )