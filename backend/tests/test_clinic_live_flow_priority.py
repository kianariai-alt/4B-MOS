from datetime import (
    datetime,
    timedelta,
    timezone,
)

from backend.app.models.treatment_session import (
    TreatmentSession,
)


def create_session(
    client,
    admin_headers,
    *,
    patient_code: str,
    session_number: int = 1,
) -> dict:
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": patient_code,
            "first_name": patient_code,
            "last_name": "Patient",
        },
    )

    assert patient_response.status_code == 201
    patient = patient_response.json()

    visit_response = client.post(
        (
            f"/api/v1/patients/"
            f"{patient['id']}/visits"
        ),
        headers=admin_headers,
        json={
            "body_region": "Knee",
        },
    )

    assert visit_response.status_code == 201
    visit = visit_response.json()

    treatment_response = client.post(
        (
            f"/api/v1/visits/"
            f"{visit['id']}/treatments"
        ),
        headers=admin_headers,
        json={
            "treatment_type": "PRP",
            "body_region": "Knee",
        },
    )

    assert treatment_response.status_code == 201
    treatment = treatment_response.json()

    session_response = client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/sessions"
        ),
        headers=admin_headers,
        json={
            "session_number": session_number,
        },
    )

    assert session_response.status_code == 201

    return session_response.json()


def transition(
    client,
    admin_headers,
    session_id: str,
    state: str,
):
    response = client.patch(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session_id}/workflow"
        ),
        headers=admin_headers,
        json={
            "operational_status": state,
        },
    )

    assert response.status_code == 200


def set_checked_in_minutes_ago(
    db_session,
    session_id: str,
    minutes: int,
):
    session = db_session.get(
        TreatmentSession,
        session_id,
    )

    assert session is not None

    session.checked_in_at = (
        datetime.now(timezone.utc)
        - timedelta(minutes=minutes)
    )

    db_session.commit()


def set_started_minutes_ago(
    db_session,
    session_id: str,
    minutes: int,
):
    session = db_session.get(
        TreatmentSession,
        session_id,
    )

    assert session is not None

    session.started_at = (
        datetime.now(timezone.utc)
        - timedelta(minutes=minutes)
    )

    db_session.commit()


def test_checked_in_queue_orders_by_priority(
    client,
    admin_headers,
    db_session,
):
    normal = create_session(
        client,
        admin_headers,
        patient_code="QUEUE-NORMAL",
    )

    attention = create_session(
        client,
        admin_headers,
        patient_code="QUEUE-ATTENTION",
    )

    urgent = create_session(
        client,
        admin_headers,
        patient_code="QUEUE-URGENT",
    )

    for session in (
        normal,
        attention,
        urgent,
    ):
        transition(
            client,
            admin_headers,
            session["id"],
            "checked_in",
        )

    set_checked_in_minutes_ago(
        db_session,
        normal["id"],
        10,
    )

    set_checked_in_minutes_ago(
        db_session,
        attention["id"],
        35,
    )

    set_checked_in_minutes_ago(
        db_session,
        urgent["id"],
        65,
    )

    response = client.get(
        "/api/v1/dashboard/live-flow",
        headers=admin_headers,
    )

    assert response.status_code == 200

    queue = response.json()[
        "checked_in"
    ]

    assert [
        item["patient_code"]
        for item in queue
    ] == [
        "QUEUE-URGENT",
        "QUEUE-ATTENTION",
        "QUEUE-NORMAL",
    ]

    assert queue[0][
        "priority_level"
    ] == "urgent"

    assert queue[1][
        "priority_level"
    ] == "attention"

    assert queue[2][
        "priority_level"
    ] == "normal"


def test_same_priority_orders_oldest_first(
    client,
    admin_headers,
    db_session,
):
    first = create_session(
        client,
        admin_headers,
        patient_code="QUEUE-FIRST",
    )

    second = create_session(
        client,
        admin_headers,
        patient_code="QUEUE-SECOND",
    )

    for session in (
        first,
        second,
    ):
        transition(
            client,
            admin_headers,
            session["id"],
            "checked_in",
        )

    set_checked_in_minutes_ago(
        db_session,
        first["id"],
        45,
    )

    set_checked_in_minutes_ago(
        db_session,
        second["id"],
        35,
    )

    response = client.get(
        "/api/v1/dashboard/live-flow",
        headers=admin_headers,
    )

    assert response.status_code == 200

    queue = response.json()[
        "checked_in"
    ]

    assert [
        item["patient_code"]
        for item in queue
    ] == [
        "QUEUE-FIRST",
        "QUEUE-SECOND",
    ]

    assert all(
        item["priority_level"]
        == "attention"
        for item in queue
    )


def test_treatment_70_minutes_is_attention(
    client,
    admin_headers,
    db_session,
):
    session = create_session(
        client,
        admin_headers,
        patient_code="TREAT-70",
    )

    for state in (
        "checked_in",
        "ready",
        "in_treatment",
    ):
        transition(
            client,
            admin_headers,
            session["id"],
            state,
        )

    set_started_minutes_ago(
        db_session,
        session["id"],
        70,
    )

    response = client.get(
        "/api/v1/dashboard/live-flow",
        headers=admin_headers,
    )

    assert response.status_code == 200

    item = response.json()[
        "in_treatment"
    ][0]

    assert (
        item["treatment_minutes"]
        >= 70
    )

    assert (
        item["priority_level"]
        == "attention"
    )

    assert (
        item["alerts"][0]["code"]
        == "PROLONGED_TREATMENT"
    )


def test_live_flow_summary_counts_alerts(
    client,
    admin_headers,
    db_session,
):
    attention = create_session(
        client,
        admin_headers,
        patient_code="SUMMARY-ATTENTION",
    )

    urgent = create_session(
        client,
        admin_headers,
        patient_code="SUMMARY-URGENT",
    )

    for session in (
        attention,
        urgent,
    ):
        transition(
            client,
            admin_headers,
            session["id"],
            "checked_in",
        )

    set_checked_in_minutes_ago(
        db_session,
        attention["id"],
        35,
    )

    set_checked_in_minutes_ago(
        db_session,
        urgent["id"],
        65,
    )

    response = client.get(
        "/api/v1/dashboard/live-flow",
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["attention_count"] == 1
    assert data["urgent_count"] == 1
    assert data["alert_count"] == 2