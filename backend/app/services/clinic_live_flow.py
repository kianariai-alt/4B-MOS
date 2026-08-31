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
    ClinicFlowAlert,
    ClinicLiveFlowItem,
    ClinicLiveFlowResponse,
)
from backend.app.services.session_workflow import (
    SessionWorkflowService,
)


APPOINTMENT_ATTENTION_MINUTES = 15
APPOINTMENT_URGENT_MINUTES = 30

WAIT_ATTENTION_MINUTES = 30
WAIT_URGENT_MINUTES = 60

READY_ATTENTION_MINUTES = 15
READY_URGENT_MINUTES = 30

TREATMENT_ATTENTION_MINUTES = 70
TREATMENT_URGENT_MINUTES = 90

DISCHARGE_ATTENTION_MINUTES = 15
DISCHARGE_URGENT_MINUTES = 30


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
    def _delay_minutes(
        expected_at: datetime | None,
        now_utc: datetime,
    ) -> int | None:
        if expected_at is None:
            return None

        expected_utc = (
            ClinicLiveFlowService._as_utc(
                expected_at
            )
        )

        if expected_utc >= now_utc:
            return 0

        return (
            ClinicLiveFlowService
            ._minutes_between(
                expected_utc,
                now_utc,
            )
        )

    @staticmethod
    def _severity(
        minutes: int | None,
        *,
        attention: int,
        urgent: int,
    ) -> str | None:
        if minutes is None:
            return None

        if minutes >= urgent:
            return "urgent"

        if minutes >= attention:
            return "attention"

        return None

    @staticmethod
    def _build_alerts(
        *,
        operational_status: str,
        scheduled_delay_minutes: int | None,
        waiting_minutes: int | None,
        ready_wait_minutes: int | None,
        treatment_minutes: int | None,
        discharge_wait_minutes: int | None,
    ) -> list[ClinicFlowAlert]:
        alerts: list[ClinicFlowAlert] = []

        if operational_status == "scheduled":
            severity = (
                ClinicLiveFlowService
                ._severity(
                    scheduled_delay_minutes,
                    attention=(
                        APPOINTMENT_ATTENTION_MINUTES
                    ),
                    urgent=(
                        APPOINTMENT_URGENT_MINUTES
                    ),
                )
            )

            if severity is not None:
                alerts.append(
                    ClinicFlowAlert(
                        code="APPOINTMENT_DELAY",
                        severity=severity,
                        message=(
                            "Patient is delayed "
                            "beyond scheduled time."
                        ),
                    )
                )

        elif operational_status == "checked_in":
            severity = (
                ClinicLiveFlowService
                ._severity(
                    waiting_minutes,
                    attention=(
                        WAIT_ATTENTION_MINUTES
                    ),
                    urgent=(
                        WAIT_URGENT_MINUTES
                    ),
                )
            )

            if severity is not None:
                alerts.append(
                    ClinicFlowAlert(
                        code="LONG_WAIT",
                        severity=severity,
                        message=(
                            "Patient has been "
                            "waiting after check-in."
                        ),
                    )
                )

        elif operational_status == "ready":
            severity = (
                ClinicLiveFlowService
                ._severity(
                    ready_wait_minutes,
                    attention=(
                        READY_ATTENTION_MINUTES
                    ),
                    urgent=(
                        READY_URGENT_MINUTES
                    ),
                )
            )

            if severity is not None:
                alerts.append(
                    ClinicFlowAlert(
                        code="READY_DELAY",
                        severity=severity,
                        message=(
                            "Patient has been ready "
                            "for treatment too long."
                        ),
                    )
                )

        elif (
            operational_status
            == "in_treatment"
        ):
            severity = (
                ClinicLiveFlowService
                ._severity(
                    treatment_minutes,
                    attention=(
                        TREATMENT_ATTENTION_MINUTES
                    ),
                    urgent=(
                        TREATMENT_URGENT_MINUTES
                    ),
                )
            )

            if severity is not None:
                alerts.append(
                    ClinicFlowAlert(
                        code="PROLONGED_TREATMENT",
                        severity=severity,
                        message=(
                            "Treatment duration "
                            "requires attention."
                        ),
                    )
                )

        elif operational_status == "completed":
            severity = (
                ClinicLiveFlowService
                ._severity(
                    discharge_wait_minutes,
                    attention=(
                        DISCHARGE_ATTENTION_MINUTES
                    ),
                    urgent=(
                        DISCHARGE_URGENT_MINUTES
                    ),
                )
            )

            if severity is not None:
                alerts.append(
                    ClinicFlowAlert(
                        code="DISCHARGE_DELAY",
                        severity=severity,
                        message=(
                            "Completed patient is "
                            "waiting for discharge."
                        ),
                    )
                )

        return alerts

    @staticmethod
    def _priority(
        alerts: list[ClinicFlowAlert],
    ) -> tuple[str, int]:
        if not alerts:
            return (
                "normal",
                0,
            )

        urgent_count = sum(
            1
            for alert in alerts
            if alert.severity == "urgent"
        )

        attention_count = sum(
            1
            for alert in alerts
            if alert.severity == "attention"
        )

        priority_score = (
            urgent_count * 100
            + attention_count * 10
        )

        if urgent_count > 0:
            return (
                "urgent",
                priority_score,
            )

        return (
            "attention",
            priority_score,
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
        scheduled_delay_minutes = None

        if (
            session.operational_status
            == "scheduled"
        ):
            scheduled_delay_minutes = (
                ClinicLiveFlowService
                ._delay_minutes(
                    session.scheduled_at,
                    now_utc,
                )
            )

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

        ready_wait_minutes = None

        if session.ready_at is not None:
            ready_end = (
                session.started_at
                or now_utc
            )

            ready_wait_minutes = (
                ClinicLiveFlowService
                ._minutes_between(
                    session.ready_at,
                    ready_end,
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

        alerts = (
            ClinicLiveFlowService
            ._build_alerts(
                operational_status=(
                    session.operational_status
                ),
                scheduled_delay_minutes=(
                    scheduled_delay_minutes
                ),
                waiting_minutes=(
                    waiting_minutes
                ),
                ready_wait_minutes=(
                    ready_wait_minutes
                ),
                treatment_minutes=(
                    treatment_minutes
                ),
                discharge_wait_minutes=(
                    discharge_wait_minutes
                ),
            )
        )

        (
            priority_level,
            priority_score,
        ) = (
            ClinicLiveFlowService
            ._priority(alerts)
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
            scheduled_at=session.scheduled_at,
            checked_in_at=session.checked_in_at,
            ready_at=session.ready_at,
            started_at=session.started_at,
            completed_at=session.completed_at,
            scheduled_delay_minutes=(
                scheduled_delay_minutes
            ),
            waiting_minutes=(
                waiting_minutes
            ),
            ready_wait_minutes=(
                ready_wait_minutes
            ),
            treatment_minutes=(
                treatment_minutes
            ),
            discharge_wait_minutes=(
                discharge_wait_minutes
            ),
            priority_level=(
                priority_level
            ),
            priority_score=(
                priority_score
            ),
            is_attention_required=(
                bool(alerts)
            ),
            alerts=alerts,
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
            ClinicLiveFlowService
            ._as_utc(value)
        )

    @staticmethod
    def _queue_sort_key(
        item: ClinicLiveFlowItem,
        timestamp: datetime | None,
    ) -> tuple[int, datetime]:
        return (
            -item.priority_score,
            ClinicLiveFlowService
            ._sort_datetime(timestamp),
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
                ._queue_sort_key(
                    item,
                    item.scheduled_at,
                )
            )
        )

        checked_in.sort(
            key=lambda item: (
                ClinicLiveFlowService
                ._queue_sort_key(
                    item,
                    item.checked_in_at,
                )
            )
        )

        ready.sort(
            key=lambda item: (
                ClinicLiveFlowService
                ._queue_sort_key(
                    item,
                    item.ready_at,
                )
            )
        )

        in_treatment.sort(
            key=lambda item: (
                ClinicLiveFlowService
                ._queue_sort_key(
                    item,
                    item.started_at,
                )
            )
        )

        awaiting_discharge.sort(
            key=lambda item: (
                ClinicLiveFlowService
                ._queue_sort_key(
                    item,
                    item.completed_at,
                )
            )
        )

        active_count = (
            len(checked_in)
            + len(ready)
            + len(in_treatment)
            + len(awaiting_discharge)
        )

        all_items = (
            scheduled
            + checked_in
            + ready
            + in_treatment
            + awaiting_discharge
        )

        attention_count = sum(
            1
            for item in all_items
            if (
                item.priority_level
                == "attention"
            )
        )

        urgent_count = sum(
            1
            for item in all_items
            if (
                item.priority_level
                == "urgent"
            )
        )

        alert_count = sum(
            len(item.alerts)
            for item in all_items
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
            attention_count=(
                attention_count
            ),
            urgent_count=urgent_count,
            alert_count=alert_count,
            scheduled=scheduled,
            checked_in=checked_in,
            ready=ready,
            in_treatment=in_treatment,
            awaiting_discharge=(
                awaiting_discharge
            ),
        )