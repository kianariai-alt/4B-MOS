def create_session(
    client,
    admin_headers,
) -> dict:
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "GUARD-001",
            "first_name": "Guard",
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
            "session_number": 1,
        },
    )

    assert session_response.status_code == 201

    return session_response.json()


def test_direct_status_change_is_rejected(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    response = client.patch(
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

    assert response.status_code == 409


def test_direct_started_at_is_rejected(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    response = client.patch(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}"
        ),
        headers=admin_headers,
        json={
            "started_at": (
                "2026-08-31T12:00:00Z"
            ),
        },
    )

    assert response.status_code == 409


def test_direct_completed_at_is_rejected(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    response = client.patch(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}"
        ),
        headers=admin_headers,
        json={
            "completed_at": (
                "2026-08-31T13:00:00Z"
            ),
        },
    )

    assert response.status_code == 409


def test_notes_update_is_still_allowed(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    response = client.patch(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}"
        ),
        headers=admin_headers,
        json={
            "notes": (
                "Patient tolerated "
                "procedure well."
            ),
        },
    )

    assert response.status_code == 200

    assert (
        response.json()["notes"]
        == "Patient tolerated "
        "procedure well."
    )

    assert (
        response.json()["status"]
        == "planned"
    )

    assert (
        response.json()[
            "operational_status"
        ]
        == "scheduled"
    )


def test_adverse_event_update_is_allowed(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    response = client.patch(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}"
        ),
        headers=admin_headers,
        json={
            "adverse_events": (
                "Transient discomfort"
            ),
        },
    )

    assert response.status_code == 200

    assert (
        response.json()[
            "adverse_events"
        ]
        == "Transient discomfort"
    )