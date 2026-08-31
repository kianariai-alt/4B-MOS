from datetime import (
    datetime,
    timedelta,
    timezone,
)

from backend.app.services.clinic_live_flow import (
    ClinicLiveFlowService,
)


def test_wait_under_30_minutes_is_normal():
    alerts = (
        ClinicLiveFlowService
        ._build_alerts(
            operational_status="checked_in",
            scheduled_delay_minutes=None,
            waiting_minutes=29,
            ready_wait_minutes=None,
            treatment_minutes=None,
            discharge_wait_minutes=None,
        )
    )

    assert alerts == []

    priority, score = (
        ClinicLiveFlowService
        ._priority(alerts)
    )

    assert priority == "normal"
    assert score == 0


def test_wait_30_minutes_requires_attention():
    alerts = (
        ClinicLiveFlowService
        ._build_alerts(
            operational_status="checked_in",
            scheduled_delay_minutes=None,
            waiting_minutes=30,
            ready_wait_minutes=None,
            treatment_minutes=None,
            discharge_wait_minutes=None,
        )
    )

    assert len(alerts) == 1

    assert (
        alerts[0].code
        == "LONG_WAIT"
    )

    assert (
        alerts[0].severity
        == "attention"
    )

    priority, score = (
        ClinicLiveFlowService
        ._priority(alerts)
    )

    assert priority == "attention"
    assert score == 10


def test_wait_60_minutes_is_urgent():
    alerts = (
        ClinicLiveFlowService
        ._build_alerts(
            operational_status="checked_in",
            scheduled_delay_minutes=None,
            waiting_minutes=60,
            ready_wait_minutes=None,
            treatment_minutes=None,
            discharge_wait_minutes=None,
        )
    )

    assert len(alerts) == 1

    assert (
        alerts[0].code
        == "LONG_WAIT"
    )

    assert (
        alerts[0].severity
        == "urgent"
    )

    priority, score = (
        ClinicLiveFlowService
        ._priority(alerts)
    )

    assert priority == "urgent"
    assert score == 100


def test_treatment_under_70_minutes_is_normal():
    alerts = (
        ClinicLiveFlowService
        ._build_alerts(
            operational_status="in_treatment",
            scheduled_delay_minutes=None,
            waiting_minutes=None,
            ready_wait_minutes=None,
            treatment_minutes=69,
            discharge_wait_minutes=None,
        )
    )

    assert alerts == []


def test_treatment_70_minutes_requires_attention():
    alerts = (
        ClinicLiveFlowService
        ._build_alerts(
            operational_status="in_treatment",
            scheduled_delay_minutes=None,
            waiting_minutes=None,
            ready_wait_minutes=None,
            treatment_minutes=70,
            discharge_wait_minutes=None,
        )
    )

    assert len(alerts) == 1

    assert (
        alerts[0].code
        == "PROLONGED_TREATMENT"
    )

    assert (
        alerts[0].severity
        == "attention"
    )

    priority, score = (
        ClinicLiveFlowService
        ._priority(alerts)
    )

    assert priority == "attention"
    assert score == 10


def test_treatment_90_minutes_is_urgent():
    alerts = (
        ClinicLiveFlowService
        ._build_alerts(
            operational_status="in_treatment",
            scheduled_delay_minutes=None,
            waiting_minutes=None,
            ready_wait_minutes=None,
            treatment_minutes=90,
            discharge_wait_minutes=None,
        )
    )

    assert len(alerts) == 1

    assert (
        alerts[0].severity
        == "urgent"
    )

    priority, score = (
        ClinicLiveFlowService
        ._priority(alerts)
    )

    assert priority == "urgent"
    assert score == 100


def test_minutes_between_calculates_duration():
    end = datetime.now(
        timezone.utc
    )

    start = (
        end
        - timedelta(minutes=70)
    )

    minutes = (
        ClinicLiveFlowService
        ._minutes_between(
            start,
            end,
        )
    )

    assert minutes == 70