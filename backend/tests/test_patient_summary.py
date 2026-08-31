from datetime import (
    datetime,
    timedelta,
    timezone,
)


def create_user_and_login(
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


def create_patient(
    client,
    admin_headers,
) -> dict:
    response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": (
                "SUMMARY-001"
            ),
            "first_name": "Summary",
            "last_name": "Patient",
        },
    )

    assert response.status_code == 201

    return response.json()


def create_visit(
    client,
    admin_headers,
    patient_id: str,
) -> dict:
    response = client.post(
        (
            f"/api/v1/patients/"
            f"{patient_id}/visits"
        ),
        headers=admin_headers,
        json={
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201

    return response.json()


def create_treatment(
    client,
    admin_headers,
    visit_id: str,
    *,
    treatment_type: str = "PRP",
) -> dict:
    response = client.post(
        (
            f"/api/v1/visits/"
            f"{visit_id}/treatments"
        ),
        headers=admin_headers,
        json={
            "treatment_type": (
                treatment_type
            ),
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201

    return response.json()


def create_session(
    client,
    admin_headers,
    treatment_id: str,
    *,
    session_number: int,
    scheduled_at: str | None = None,
) -> dict:
    payload = {
        "session_number": session_number,
        "body_region": "Knee",
    }

    if scheduled_at is not None:
        payload["scheduled_at"] = (
            scheduled_at
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


def test_summary_requires_authentication(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{patient['id']}"
            "/clinical-summary"
        )
    )

    assert response.status_code == 401


def test_viewer_can_read_summary(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    viewer_headers = (
        create_user_and_login(
            client,
            admin_headers,
            username="summaryviewer",
            role="viewer",
        )
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{patient['id']}"
            "/clinical-summary"
        ),
        headers=viewer_headers,
    )

    assert response.status_code == 200


def test_empty_patient_summary(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{patient['id']}"
            "/clinical-summary"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total_visits"] == 0
    assert data["total_treatments"] == 0
    assert data["total_sessions"] == 0

    assert data["latest_visit"] is None

    assert (
        data["next_scheduled_session"]
        is None
    )

    assert (
        data["last_completed_session"]
        is None
    )


def test_summary_aggregates_clinical_chain(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    visit = create_visit(
        client,
        admin_headers,
        patient["id"],
    )

    treatment = create_treatment(
        client,
        admin_headers,
        visit["id"],
    )

    create_session(
        client,
        admin_headers,
        treatment["id"],
        session_number=1,
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{patient['id']}"
            "/clinical-summary"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["total_visits"] == 1

    assert (
        data["open_visit_count"]
        == 1
    )

    assert (
        data["total_treatments"]
        == 1
    )

    assert (
        data["active_treatment_count"]
        == 1
    )

    assert data["total_sessions"] == 1

    assert (
        data["latest_visit"]["id"]
        == visit["id"]
    )

    assert (
        data["treatment_type_counts"][
            "PRP"
        ]
        == 1
    )


def test_only_active_treatments_are_listed(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    visit = create_visit(
        client,
        admin_headers,
        patient["id"],
    )

    active = create_treatment(
        client,
        admin_headers,
        visit["id"],
        treatment_type="PRP",
    )

    completed = create_treatment(
        client,
        admin_headers,
        visit["id"],
        treatment_type="ACS",
    )

    update_response = client.patch(
        (
            f"/api/v1/treatments/"
            f"{completed['id']}"
        ),
        headers=admin_headers,
        json={
            "status": "completed",
        },
    )

    assert (
        update_response.status_code
        == 200
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{patient['id']}"
            "/clinical-summary"
        ),
        headers=admin_headers,
    )

    data = response.json()

    ids = {
        item["id"]
        for item in data[
            "active_treatments"
        ]
    }

    assert active["id"] in ids

    assert (
        completed["id"]
        not in ids
    )

    assert (
        data[
            "completed_treatment_count"
        ]
        == 1
    )


def test_next_session_and_overdue_count(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    visit = create_visit(
        client,
        admin_headers,
        patient["id"],
    )

    treatment = create_treatment(
        client,
        admin_headers,
        visit["id"],
    )

    now = datetime.now(
        timezone.utc
    )

    past = (
        now
        - timedelta(days=2)
    ).isoformat()

    near_future = (
        now
        + timedelta(days=2)
    ).isoformat()

    far_future = (
        now
        + timedelta(days=10)
    ).isoformat()

    create_session(
        client,
        admin_headers,
        treatment["id"],
        session_number=1,
        scheduled_at=past,
    )

    nearest = create_session(
        client,
        admin_headers,
        treatment["id"],
        session_number=2,
        scheduled_at=near_future,
    )

    create_session(
        client,
        admin_headers,
        treatment["id"],
        session_number=3,
        scheduled_at=far_future,
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{patient['id']}"
            "/clinical-summary"
        ),
        headers=admin_headers,
    )

    data = response.json()

    assert (
        data[
            "overdue_planned_session_count"
        ]
        == 1
    )

    assert (
        data[
            "next_scheduled_session"
        ]["id"]
        == nearest["id"]
    )

    flag_codes = {
        flag["code"]
        for flag in data[
            "operational_flags"
        ]
    }

    assert (
        "overdue_planned_sessions"
        in flag_codes
    )


def test_last_completed_session(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    visit = create_visit(
        client,
        admin_headers,
        patient["id"],
    )

    treatment = create_treatment(
        client,
        admin_headers,
        visit["id"],
    )

    session = create_session(
        client,
        admin_headers,
        treatment["id"],
        session_number=1,
    )

    start_response = client.patch(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}"
        ),
        headers=admin_headers,
        json={
            "status": "in_progress",
        },
    )

    assert (
        start_response.status_code
        == 200
    )

    complete_response = client.patch(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}"
        ),
        headers=admin_headers,
        json={
            "status": "completed",
        },
    )

    assert (
        complete_response.status_code
        == 200
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{patient['id']}"
            "/clinical-summary"
        ),
        headers=admin_headers,
    )

    data = response.json()

    assert (
        data[
            "completed_session_count"
        ]
        == 1
    )

    assert (
        data[
            "last_completed_session"
        ]["id"]
        == session["id"]
    )


def test_adverse_event_flag(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    visit = create_visit(
        client,
        admin_headers,
        patient["id"],
    )

    treatment = create_treatment(
        client,
        admin_headers,
        visit["id"],
    )

    session = create_session(
        client,
        admin_headers,
        treatment["id"],
        session_number=1,
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
        (
            f"/api/v1/patients/"
            f"{patient['id']}"
            "/clinical-summary"
        ),
        headers=admin_headers,
    )

    data = response.json()

    assert (
        data[
            "sessions_with_adverse_events"
        ]
        == 1
    )

    codes = {
        flag["code"]
        for flag in data[
            "operational_flags"
        ]
    }

    assert (
        "documented_adverse_events"
        in codes
    )


def test_missing_patient_summary_returns_404(
    client,
    admin_headers,
):
    response = client.get(
        (
            "/api/v1/patients/"
            "not-a-real-patient/"
            "clinical-summary"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 404