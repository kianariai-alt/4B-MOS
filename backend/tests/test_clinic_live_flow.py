from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from backend.app.core.config import settings


def login_role(
    client,
    admin_headers,
    *,
    username: str,
    role: str,
) -> dict:
    password = "StrongPass123"

    response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": username,
            "display_name": username.title(),
            "password": password,
            "role": role,
        },
    )

    assert response.status_code == 201

    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": password,
        },
    )

    assert response.status_code == 200

    return {
        "Authorization": (
            "Bearer "
            + response.json()[
                "access_token"
            ]
        )
    }


def create_session(
    client,
    admin_headers,
) -> dict:
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "LIVE-001",
            "first_name": "Live",
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

    response = client.post(
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

    assert response.status_code == 201

    return response.json()


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

    return response.json()


def live_flow(
    client,
    headers,
) -> dict:
    response = client.get(
        "/api/v1/dashboard/live-flow",
        headers=headers,
    )

    assert response.status_code == 200

    return response.json()


def action_codes(
    item: dict,
) -> list[str]:
    return [
        action["code"]
        for action in item[
            "allowed_actions"
        ]
    ]


def test_live_flow_requires_authentication(
    client,
):
    response = client.get(
        "/api/v1/dashboard/live-flow"
    )

    assert response.status_code == 401


def test_viewer_cannot_read_live_flow(
    client,
    admin_headers,
):
    headers = login_role(
        client,
        admin_headers,
        username="liveviewer",
        role="viewer",
    )

    response = client.get(
        "/api/v1/dashboard/live-flow",
        headers=headers,
    )

    assert response.status_code == 403


def test_operator_can_read_live_flow(
    client,
    admin_headers,
):
    headers = login_role(
        client,
        admin_headers,
        username="liveoperator",
        role="operator",
    )

    response = client.get(
        "/api/v1/dashboard/live-flow",
        headers=headers,
    )

    assert response.status_code == 200


def test_scheduled_session_is_in_live_flow(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    data = live_flow(
        client,
        admin_headers,
    )

    assert data["scheduled_count"] == 1

    item = data["scheduled"][0]

    assert item["session_id"] == session["id"]

    assert (
        item["operational_status"]
        == "scheduled"
    )

    assert action_codes(item) == [
        "check_in",
        "cancel",
    ]


def test_checked_in_patient_shows_wait_time(
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

    data = live_flow(
        client,
        admin_headers,
    )

    assert data["checked_in_count"] == 1
    assert data["scheduled_count"] == 0

    item = data["checked_in"][0]

    assert item["waiting_minutes"] >= 0

    assert action_codes(item) == [
        "mark_ready",
        "cancel",
    ]


def test_ready_patient_is_in_ready_queue(
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

    data = live_flow(
        client,
        admin_headers,
    )

    assert data["ready_count"] == 1

    item = data["ready"][0]

    assert item["waiting_minutes"] >= 0

    assert action_codes(item) == [
        "start_treatment",
        "cancel",
    ]


def test_in_treatment_tracks_duration(
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

    data = live_flow(
        client,
        admin_headers,
    )

    assert (
        data["in_treatment_count"]
        == 1
    )

    item = data["in_treatment"][0]

    assert item["status"] == "in_progress"
    assert item["waiting_minutes"] >= 0
    assert item["treatment_minutes"] >= 0

    assert action_codes(item) == [
        "complete",
        "cancel",
    ]


def test_completed_waits_for_discharge(
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

    data = live_flow(
        client,
        admin_headers,
    )

    assert (
        data["awaiting_discharge_count"]
        == 1
    )

    item = data[
        "awaiting_discharge"
    ][0]

    assert item["status"] == "completed"

    assert (
        item["discharge_wait_minutes"]
        >= 0
    )

    assert action_codes(item) == [
        "discharge",
    ]

    transition(
        client,
        admin_headers,
        session["id"],
        "discharged",
    )

    data = live_flow(
        client,
        admin_headers,
    )

    ids = {
        item["session_id"]
        for queue in (
            "scheduled",
            "checked_in",
            "ready",
            "in_treatment",
            "awaiting_discharge",
        )
        for item in data[queue]
    }

    assert session["id"] not in ids