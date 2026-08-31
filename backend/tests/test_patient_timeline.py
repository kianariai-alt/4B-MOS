from datetime import datetime


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
            "display_name": username.title(),
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


def create_clinical_chain(
    client,
    admin_headers,
) -> dict:
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": (
                "TIMELINE-001"
            ),
            "first_name": "Timeline",
            "last_name": "Patient",
        },
    )

    assert (
        patient_response.status_code
        == 201
    )

    patient = (
        patient_response.json()
    )

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

    treatment = (
        treatment_response.json()
    )

    session_response = client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/sessions"
        ),
        headers=admin_headers,
        json={
            "session_number": 1,
            "body_region": "Knee",
        },
    )

    assert (
        session_response.status_code
        == 201
    )

    session = session_response.json()

    return {
        "patient": patient,
        "visit": visit,
        "treatment": treatment,
        "session": session,
    }


def test_timeline_requires_authentication(
    client,
    admin_headers,
):
    chain = create_clinical_chain(
        client,
        admin_headers,
    )

    patient = chain["patient"]

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{patient['id']}/timeline"
        )
    )

    assert response.status_code == 401


def test_viewer_cannot_read_timeline(
    client,
    admin_headers,
):
    chain = create_clinical_chain(
        client,
        admin_headers,
    )

    viewer_headers = (
        create_user_and_login(
            client,
            admin_headers,
            username="timelineviewer",
            role="viewer",
        )
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{chain['patient']['id']}"
            "/timeline"
        ),
        headers=viewer_headers,
    )

    assert response.status_code == 403


def test_operator_cannot_read_timeline(
    client,
    admin_headers,
):
    chain = create_clinical_chain(
        client,
        admin_headers,
    )

    operator_headers = (
        create_user_and_login(
            client,
            admin_headers,
            username="timelineoperator",
            role="operator",
        )
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{chain['patient']['id']}"
            "/timeline"
        ),
        headers=operator_headers,
    )

    assert response.status_code == 403


def test_nurse_can_read_timeline(
    client,
    admin_headers,
):
    chain = create_clinical_chain(
        client,
        admin_headers,
    )

    nurse_headers = (
        create_user_and_login(
            client,
            admin_headers,
            username="timelinenurse",
            role="nurse",
        )
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{chain['patient']['id']}"
            "/timeline"
        ),
        headers=nurse_headers,
    )

    assert response.status_code == 200


def test_timeline_contains_clinical_chain(
    client,
    admin_headers,
):
    chain = create_clinical_chain(
        client,
        admin_headers,
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{chain['patient']['id']}"
            "/timeline"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["patient_id"]
        == chain["patient"]["id"]
    )

    item_types = {
        item["item_type"]
        for item in data["items"]
    }

    assert "visit" in item_types
    assert "treatment" in item_types
    assert "session" in item_types
    assert "audit" in item_types

    event_types = {
        item["event_type"]
        for item in data["items"]
    }

    assert (
        "patient_created"
        in event_types
    )

    assert (
        "visit_created"
        in event_types
    )

    assert (
        "treatment_created"
        in event_types
    )

    assert (
        "session_created"
        in event_types
    )


def test_timeline_audit_contains_actor(
    client,
    admin_headers,
):
    chain = create_clinical_chain(
        client,
        admin_headers,
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{chain['patient']['id']}"
            "/timeline"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    audit_items = [
        item
        for item in response.json()[
            "items"
        ]
        if item["item_type"]
        == "audit"
    ]

    assert len(audit_items) >= 4

    assert all(
        item["actor_username"]
        == "testadmin"
        for item in audit_items
    )

    assert all(
        item["actor_role"]
        == "admin"
        for item in audit_items
    )


def test_timeline_is_chronological(
    client,
    admin_headers,
):
    chain = create_clinical_chain(
        client,
        admin_headers,
    )

    response = client.get(
        (
            f"/api/v1/patients/"
            f"{chain['patient']['id']}"
            "/timeline"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    items = response.json()["items"]

    timestamps = [
        datetime.fromisoformat(
            item["timestamp"].replace(
                "Z",
                "+00:00",
            )
        )
        for item in items
    ]

    assert timestamps == sorted(
        timestamps
    )


def test_missing_patient_timeline_returns_404(
    client,
    admin_headers,
):
    response = client.get(
        (
            "/api/v1/patients/"
            "not-a-real-patient/timeline"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 404