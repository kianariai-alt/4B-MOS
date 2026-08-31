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
from backend.app.schemas.clinic_live_flow import (
    ClinicLiveFlowItem,
    ClinicLiveFlowResponse,
)
from backend.app.services.session_workflow import (
    SessionWorkflowService,
)


class ClinicLiveFlowService:
    @staticmethod
    def _as_utc(
        value: datetime,
    ) -> datetime:
        if value.tzinfo is None:
            return value.replace(
                tzinfo=timezone.utc,
            )

        return value.astimezone(
            timezone.utc,
        )

    @staticmethod
    def _minutes_between(
        start: datetime | None,
        end: datetime,
    ) -> int | None:
        if start is None:
            return None

        start_utc = (
            ClinicLiveFlowService._as_utc(
                start
            )
        )

        end_utc = (
            ClinicLiveFlowService._as_utc(
                end
            )
        )

        seconds = (
            end_utc - start_utc
        ).total_seconds()

        return max(
            0,
            int(seconds // 60),
        )

    @staticmethod
    def _make_item(
        *,
        session: TreatmentSession,
        treatment: Treatment,
        visit: Visit,
        patient: Patient,
        now_utc: datetime,
    ) -> ClinicLiveFlowItem:
        waiting_minutes = None

        if session.checked_in_at is not None:
            waiting_end = (
                session.started_at
                or now_utc
            )

            waiting_minutes = (
                ClinicLiveFlowService
                ._minutes_between(
                    session.checked_in_at,
                    waiting_end,
                )
            )

        treatment_minutes = None

        if session.started_at is not None:
            treatment_end = (
                session.completed_at
                or now_utc
            )

            treatment_minutes = (
                ClinicLiveFlowService
                ._minutes_between(
                    session.started_at,
                    treatment_end,
                )
            )

        discharge_wait_minutes = None

        if (
            session.operational_status
            == "completed"
            and session.completed_at
            is not None
        ):
            discharge_wait_minutes = (
                ClinicLiveFlowService
                ._minutes_between(
                    session.completed_at,
                    now_utc,
                )
            )

        return ClinicLiveFlowItem(
            session_id=session.id,
            treatment_id=treatment.id,
            visit_id=visit.id,
            patient_id=patient.id,
            patient_code=patient.patient_code,
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
            operational_status=(
                session.operational_status
            ),
            scheduled_at=(
                session.scheduled_at
            ),
            checked_in_at=(
                session.checked_in_at
            ),
            ready_at=session.ready_at,
            started_at=session.started_at,
            completed_at=(
                session.completed_at
            ),
            waiting_minutes=(
                waiting_minutes
            ),
            treatment_minutes=(
                treatment_minutes
            ),
            discharge_wait_minutes=(
                discharge_wait_minutes
            ),
            allowed_actions=(
                SessionWorkflowService
                .allowed_actions(
                    session.operational_status
                )
            ),
        )

    @staticmethod
    def _sort_datetime(
        value: datetime | None,
    ) -> datetime:
        if value is None:
            return datetime.max.replace(
                tzinfo=timezone.utc,
            )

        return (
            ClinicLiveFlowService._as_utc(
                value
            )
        )

    @staticmethod
    def get_live_flow(
        db: Session,
    ) -> ClinicLiveFlowResponse:
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

        visible_statuses = (
            "scheduled",
            "checked_in",
            "ready",
            "in_treatment",
            "completed",
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
            .where(
                TreatmentSession
                .operational_status
                .in_(visible_statuses)
            )
        )

        rows = db.execute(
            statement
        ).all()

        scheduled = []
        checked_in = []
        ready = []
        in_treatment = []
        awaiting_discharge = []

        for (
            session,
            treatment,
            visit,
            patient,
        ) in rows:
            operational_status = (
                session.operational_status
            )

            if operational_status == "scheduled":
                if session.scheduled_at is None:
                    continue

                scheduled_utc = (
                    ClinicLiveFlowService
                    ._as_utc(
                        session.scheduled_at
                    )
                )

                if not (
                    day_start_utc
                    <= scheduled_utc
                    < day_end_utc
                ):
                    continue

            item = (
                ClinicLiveFlowService
                ._make_item(
                    session=session,
                    treatment=treatment,
                    visit=visit,
                    patient=patient,
                    now_utc=now_utc,
                )
            )

            if operational_status == "scheduled":
                scheduled.append(item)

            elif operational_status == "checked_in":
                checked_in.append(item)

            elif operational_status == "ready":
                ready.append(item)

            elif (
                operational_status
                == "in_treatment"
            ):
                in_treatment.append(item)

            elif operational_status == "completed":
                awaiting_discharge.append(
                    item
                )

        scheduled.sort(
            key=lambda item: (
                ClinicLiveFlowService
                ._sort_datetime(
                    item.scheduled_at
                )
            )
        )

        checked_in.sort(
            key=lambda item: (
                ClinicLiveFlowService
                ._sort_datetime(
                    item.checked_in_at
                )
            )
        )

        ready.sort(
            key=lambda item: (
                ClinicLiveFlowService
                ._sort_datetime(
                    item.ready_at
                )
            )
        )

        in_treatment.sort(
            key=lambda item: (
                ClinicLiveFlowService
                ._sort_datetime(
                    item.started_at
                )
            )
        )

        awaiting_discharge.sort(
            key=lambda item: (
                ClinicLiveFlowService
                ._sort_datetime(
                    item.completed_at
                )
            )
        )

        active_count = (
            len(checked_in)
            + len(ready)
            + len(in_treatment)
            + len(awaiting_discharge)
        )

        return ClinicLiveFlowResponse(
            generated_at=now_utc,
            clinic_timezone=(
                settings.CLINIC_TIMEZONE
            ),
            local_date=now_local.date(),
            scheduled_count=len(
                scheduled
            ),
            checked_in_count=len(
                checked_in
            ),
            ready_count=len(ready),
            in_treatment_count=len(
                in_treatment
            ),
            awaiting_discharge_count=len(
                awaiting_discharge
            ),
            active_count=active_count,
            scheduled=scheduled,
            checked_in=checked_in,
            ready=ready,
            in_treatment=in_treatment,
            awaiting_discharge=(
                awaiting_discharge
            ),
        )