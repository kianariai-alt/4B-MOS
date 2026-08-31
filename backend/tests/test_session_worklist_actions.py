from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from backend.app.core.config import settings


def create_session(
    client,
    admin_headers,
) -> dict:
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "ACTION-001",
            "first_name": "Action",
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

    clinic_tz = ZoneInfo(
        settings.CLINIC_TIMEZONE
    )

    now_local = datetime.now(
        timezone.utc
    ).astimezone(
        clinic_tz
    )

    scheduled_at = now_local.replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
    )

    session_response = client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/sessions"
        ),
        headers=admin_headers,
        json={
            "session_number": 1,
            "scheduled_at": (
                scheduled_at.isoformat()
            ),
        },
    )

    assert session_response.status_code == 201

    return session_response.json()


def transition(
    client,
    admin_headers,
    session_id: str,
    state: str,
) -> dict:
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

    return response.json()


def get_worklist_item(
    client,
    admin_headers,
    session_id: str,
) -> dict:
    response = client.get(
        "/api/v1/dashboard/worklist",
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    items = (
        data["today"]
        + data["overdue"]
        + data["upcoming"]
        + data["unscheduled"]
    )

    return next(
        item
        for item in items
        if item["session_id"] == session_id
    )


def action_codes(
    item: dict,
) -> list[str]:
    return [
        action["code"]
        for action in item["allowed_actions"]
    ]


def test_scheduled_actions(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    item = get_worklist_item(
        client,
        admin_headers,
        session["id"],
    )

    assert (
        item["operational_status"]
        == "scheduled"
    )

    assert action_codes(item) == [
        "check_in",
        "cancel",
    ]

    assert (
        item["allowed_actions"][0][
            "target_status"
        ]
        == "checked_in"
    )

    assert (
        item["allowed_actions"][0][
            "is_primary"
        ]
        is True
    )


def test_checked_in_actions(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    transition(
        client,
        admin_headers,
        session["id"],
        "checked_in",
    )

    item = get_worklist_item(
        client,
        admin_headers,
        session["id"],
    )

    assert (
        item["operational_status"]
        == "checked_in"
    )

    assert action_codes(item) == [
        "mark_ready",
        "cancel",
    ]


def test_ready_actions(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    for state in (
        "checked_in",
        "ready",
    ):
        transition(
            client,
            admin_headers,
            session["id"],
            state,
        )

    item = get_worklist_item(
        client,
        admin_headers,
        session["id"],
    )

    assert (
        item["operational_status"]
        == "ready"
    )

    assert action_codes(item) == [
        "start_treatment",
        "cancel",
    ]


def test_in_treatment_actions(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
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

    item = get_worklist_item(
        client,
        admin_headers,
        session["id"],
    )

    assert (
        item["operational_status"]
        == "in_treatment"
    )

    assert item["status"] == "in_progress"

    assert action_codes(item) == [
        "complete",
        "cancel",
    ]


def test_completed_actions(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    for state in (
        "checked_in",
        "ready",
        "in_treatment",
        "completed",
    ):
        transition(
            client,
            admin_headers,
            session["id"],
            state,
        )

    item = get_worklist_item(
        client,
        admin_headers,
        session["id"],
    )

    assert (
        item["operational_status"]
        == "completed"
    )

    assert item["status"] == "completed"

    assert action_codes(item) == [
        "discharge",
    ]


def test_discharged_has_no_actions(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    for state in (
        "checked_in",
        "ready",
        "in_treatment",
        "completed",
        "discharged",
    ):
        transition(
            client,
            admin_headers,
            session["id"],
            state,
        )

    item = get_worklist_item(
        client,
        admin_headers,
        session["id"],
    )

    assert (
        item["operational_status"]
        == "discharged"
    )

    assert item["status"] == "completed"

    assert item["allowed_actions"] == []


def test_cancelled_has_no_actions(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    transition(
        client,
        admin_headers,
        session["id"],
        "cancelled",
    )

    item = get_worklist_item(
        client,
        admin_headers,
        session["id"],
    )

    assert (
        item["operational_status"]
        == "cancelled"
    )

    assert item["status"] == "cancelled"

    assert item["allowed_actions"] == []