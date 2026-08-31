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


def create_clinical_data(
    client,
    admin_headers,
):
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "DASH-001",
            "first_name": "Dashboard",
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
    scheduled_at: datetime,
):
    response = client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment_id}/sessions"
        ),
        headers=admin_headers,
        json={
            "session_number": number,
            "scheduled_at": (
                scheduled_at.isoformat()
            ),
        },
    )

    assert response.status_code == 201

    return response.json()


def test_dashboard_requires_authentication(
    client,
):
    response = client.get(
        "/api/v1/dashboard/operations"
    )

    assert response.status_code == 401


def test_viewer_cannot_read_dashboard(
    client,
    admin_headers,
):
    headers = login_role(
        client,
        admin_headers,
        username="dashboardviewer",
        role="viewer",
    )

    response = client.get(
        "/api/v1/dashboard/operations",
        headers=headers,
    )

    assert response.status_code == 403


def test_operator_can_read_dashboard(
    client,
    admin_headers,
):
    headers = login_role(
        client,
        admin_headers,
        username="dashboardoperator",
        role="operator",
    )

    response = client.get(
        "/api/v1/dashboard/operations",
        headers=headers,
    )

    assert response.status_code == 200


def test_empty_dashboard(
    client,
    admin_headers,
):
    response = client.get(
        "/api/v1/dashboard/operations",
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total_patients"] == 0
    assert data["total_visits"] == 0
    assert data["total_treatments"] == 0
    assert data["total_sessions"] == 0

    assert (
        data["clinic_timezone"]
        == settings.CLINIC_TIMEZONE
    )


def test_dashboard_aggregates_clinical_data(
    client,
    admin_headers,
):
    chain = create_clinical_data(
        client,
        admin_headers,
    )

    response = client.get(
        "/api/v1/dashboard/operations",
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total_patients"] == 1

    assert (
        data["active_patient_count"]
        == 1
    )

    assert data["total_visits"] == 1

    assert (
        data["open_visit_count"]
        == 1
    )

    assert data["total_treatments"] == 1

    assert (
        data["active_treatment_count"]
        == 1
    )

    assert (
        data["treatment_type_counts"][
            "PRP"
        ]
        == 1
    )

    assert (
        chain["treatment"]["status"]
        == "planned"
    )


def test_dashboard_session_schedule_counts(
    client,
    admin_headers,
):
    chain = create_clinical_data(
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

    today_future = (
        now_local
        + timedelta(minutes=30)
    )

    future = (
        now_local
        + timedelta(days=3)
    )

    past = (
        now_local
        - timedelta(days=2)
    )

    create_session(
        client,
        admin_headers,
        chain["treatment"]["id"],
        number=1,
        scheduled_at=today_future,
    )

    create_session(
        client,
        admin_headers,
        chain["treatment"]["id"],
        number=2,
        scheduled_at=future,
    )

    create_session(
        client,
        admin_headers,
        chain["treatment"]["id"],
        number=3,
        scheduled_at=past,
    )

    response = client.get(
        "/api/v1/dashboard/operations",
        headers=admin_headers,
    )

    data = response.json()

    assert data["total_sessions"] == 3

    assert (
        data[
            "upcoming_planned_sessions"
        ]
        == 2
    )

    assert (
        data[
            "overdue_planned_sessions"
        ]
        == 1
    )

    flag_codes = {
        item["code"]
        for item in data[
            "operational_flags"
        ]
    }

    assert (
        "overdue_planned_sessions"
        in flag_codes
    )


def test_dashboard_counts_audit_activity(
    client,
    admin_headers,
):
    create_clinical_data(
        client,
        admin_headers,
    )

    response = client.get(
        "/api/v1/dashboard/operations",
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["audit_events_last_24h"]
        >= 3
    )

    assert (
        data[
            "audit_event_type_counts"
        ]["patient_created"]
        == 1
    )

    assert (
        data[
            "audit_event_type_counts"
        ]["visit_created"]
        == 1
    )

    assert (
        data[
            "audit_event_type_counts"
        ]["treatment_created"]
        == 1
    )