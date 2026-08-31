from datetime import (
    datetime,
    timedelta,
    timezone,
)
from zoneinfo import ZoneInfo

from backend.app.core.config import (
    settings,
)


def login_role(
    client,
    admin_headers,
    *,
    username: str,
    role: str,
) -> dict:
    password = "StrongPass123"

    create_response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": username,
            "display_name": (
                username.title()
            ),
            "password": password,
            "role": role,
        },
    )

    assert (
        create_response.status_code
        == 201
    )

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": password,
        },
    )

    assert (
        login_response.status_code
        == 200
    )

    token = login_response.json()[
        "access_token"
    ]

    return {
        "Authorization": (
            f"Bearer {token}"
        ),
    }


def create_chain(
    client,
    admin_headers,
) -> dict:
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": (
                "WORKLIST-001"
            ),
            "first_name": "Worklist",
            "last_name": "Patient",
        },
    )

    assert (
        patient_response.status_code
        == 201
    )

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

    assert (
        visit_response.status_code
        == 201
    )

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

    assert (
        treatment_response.status_code
        == 201
    )

    return {
        "patient": patient,
        "visit": visit,
        "treatment": (
            treatment_response.json()
        ),
    }


def create_session(
    client,
    admin_headers,
    treatment_id: str,
    *,
    number: int,
    scheduled_at: datetime | None,
) -> dict:
    payload = {
        "session_number": number,
        "body_region": "Knee",
    }

    if scheduled_at is not None:
        payload["scheduled_at"] = (
            scheduled_at.isoformat()
        )

    response = client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment_id}/sessions"
        ),
        headers=admin_headers,
        json=payload,
    )

    assert response.status_code == 201

    return response.json()


def test_worklist_requires_authentication(
    client,
):
    response = client.get(
        "/api/v1/dashboard/worklist"
    )

    assert response.status_code == 401


def test_viewer_cannot_read_worklist(
    client,
    admin_headers,
):
    headers = login_role(
        client,
        admin_headers,
        username="worklistviewer",
        role="viewer",
    )

    response = client.get(
        "/api/v1/dashboard/worklist",
        headers=headers,
    )

    assert response.status_code == 403


def test_operator_can_read_worklist(
    client,
    admin_headers,
):
    headers = login_role(
        client,
        admin_headers,
        username="worklistoperator",
        role="operator",
    )

    response = client.get(
        "/api/v1/dashboard/worklist",
        headers=headers,
    )

    assert response.status_code == 200


def test_empty_worklist(
    client,
    admin_headers,
):
    response = client.get(
        "/api/v1/dashboard/worklist",
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["today_count"] == 0
    assert data["overdue_count"] == 0
    assert data["upcoming_count"] == 0
    assert data["unscheduled_count"] == 0


def test_session_scheduled_today_is_listed(
    client,
    admin_headers,
):
    chain = create_chain(
        client,
        admin_headers,
    )

    clinic_tz = ZoneInfo(
        settings.CLINIC_TIMEZONE
    )

    now_local = datetime.now(
        timezone.utc
    ).astimezone(
        clinic_tz
    )

    today_noon = now_local.replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
    )

    session = create_session(
        client,
        admin_headers,
        chain["treatment"]["id"],
        number=1,
        scheduled_at=today_noon,
    )

    response = client.get(
        "/api/v1/dashboard/worklist",
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    ids = {
        item["session_id"]
        for item in data["today"]
    }

    assert session["id"] in ids

    item = next(
        item
        for item in data["today"]
        if item["session_id"]
        == session["id"]
    )

    assert (
        item["patient_code"]
        == "WORKLIST-001"
    )

    assert (
        item["treatment_type"]
        == "PRP"
    )


def test_worklist_classifies_sessions(
    client,
    admin_headers,
):
    chain = create_chain(
        client,
        admin_headers,
    )

    clinic_tz = ZoneInfo(
        settings.CLINIC_TIMEZONE
    )

    now_local = datetime.now(
        timezone.utc
    ).astimezone(
        clinic_tz
    )

    yesterday = (
        now_local
        - timedelta(days=1)
    ).replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
    )

    future = (
        now_local
        + timedelta(days=2)
    ).replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
    )

    overdue = create_session(
        client,
        admin_headers,
        chain["treatment"]["id"],
        number=1,
        scheduled_at=yesterday,
    )

    upcoming = create_session(
        client,
        admin_headers,
        chain["treatment"]["id"],
        number=2,
        scheduled_at=future,
    )

    unscheduled = create_session(
        client,
        admin_headers,
        chain["treatment"]["id"],
        number=3,
        scheduled_at=None,
    )

    response = client.get(
        "/api/v1/dashboard/worklist",
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    overdue_ids = {
        item["session_id"]
        for item in data["overdue"]
    }

    upcoming_ids = {
        item["session_id"]
        for item in data["upcoming"]
    }

    unscheduled_ids = {
        item["session_id"]
        for item in data["unscheduled"]
    }

    assert overdue["id"] in overdue_ids
    assert upcoming["id"] in upcoming_ids

    assert (
        unscheduled["id"]
        in unscheduled_ids
    )


def test_worklist_respects_horizon(
    client,
    admin_headers,
):
    chain = create_chain(
        client,
        admin_headers,
    )

    clinic_tz = ZoneInfo(
        settings.CLINIC_TIMEZONE
    )

    now_local = datetime.now(
        timezone.utc
    ).astimezone(
        clinic_tz
    )

    far_future = (
        now_local
        + timedelta(days=10)
    ).replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
    )

    session = create_session(
        client,
        admin_headers,
        chain["treatment"]["id"],
        number=1,
        scheduled_at=far_future,
    )

    response = client.get(
        "/api/v1/dashboard/worklist"
        "?days=3",
        headers=admin_headers,
    )

    assert response.status_code == 200

    ids = {
        item["session_id"]
        for item in response.json()[
            "upcoming"
        ]
    }

    assert session["id"] not in ids


def test_worklist_marks_adverse_event(
    client,
    admin_headers,
):
    chain = create_chain(
        client,
        admin_headers,
    )

    clinic_tz = ZoneInfo(
        settings.CLINIC_TIMEZONE
    )

    now_local = datetime.now(
        timezone.utc
    ).astimezone(
        clinic_tz
    )

    today_noon = now_local.replace(
        hour=12,
        minute=0,
        second=0,
        microsecond=0,
    )

    session = create_session(
        client,
        admin_headers,
        chain["treatment"]["id"],
        number=1,
        scheduled_at=today_noon,
    )

    update_response = client.patch(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}"
        ),
        headers=admin_headers,
        json={
            "adverse_events": (
                "Documented event"
            ),
        },
    )

    assert (
        update_response.status_code
        == 200
    )

    response = client.get(
        "/api/v1/dashboard/worklist",
        headers=admin_headers,
    )

    assert response.status_code == 200

    item = next(
        item
        for item in response.json()[
            "today"
        ]
        if item["session_id"]
        == session["id"]
    )

    assert (
        item[
            "has_documented_adverse_event"
        ]
        is True
    )