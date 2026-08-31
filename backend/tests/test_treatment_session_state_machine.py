import pytest


@pytest.fixture(autouse=True)
def authenticate_session_tests(
    client,
    admin_headers,
):
    create_response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": "statedoctor",
            "display_name": "State Doctor",
            "password": "StrongPass123",
            "role": "physician",
        },
    )

    assert create_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "statedoctor",
            "password": "StrongPass123",
        },
    )

    assert login_response.status_code == 200

    token = login_response.json()[
        "access_token"
    ]

    client.headers.update(
        {
            "Authorization": (
                f"Bearer {token}"
            ),
        }
    )


def create_patient(
    client,
) -> dict:
    response = client.post(
        "/api/v1/patients",
        json={
            "patient_code": "STATE-PAT-001",
            "first_name": "State",
            "last_name": "Patient",
        },
    )

    assert response.status_code == 201

    return response.json()


def create_visit(
    client,
) -> dict:
    patient = create_patient(client)

    response = client.post(
        (
            f"/api/v1/patients/"
            f"{patient['id']}/visits"
        ),
        json={
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201

    return response.json()


def create_treatment(
    client,
) -> dict:
    visit = create_visit(client)

    response = client.post(
        (
            f"/api/v1/visits/"
            f"{visit['id']}/treatments"
        ),
        json={
            "treatment_type": "PRP",
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201

    return response.json()


def create_treatment_with_session(
    client,
) -> dict:
    treatment = create_treatment(
        client
    )

    response = client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/sessions"
        ),
        json={
            "session_number": 1,
        },
    )

    assert response.status_code == 201

    return response.json()


def transition(
    client,
    session_id: str,
    operational_status: str,
):
    return client.patch(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session_id}/workflow"
        ),
        json={
            "operational_status": (
                operational_status
            ),
        },
    )


def test_session_creation_writes_audit_log(
    client,
):
    session = (
        create_treatment_with_session(
            client
        )
    )

    response = client.get(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}/audit-logs"
        )
    )

    assert response.status_code == 200

    logs = response.json()

    assert len(logs) == 1

    assert (
        logs[0]["event_type"]
        == "session_created"
    )

    assert logs[0]["from_state"] is None

    assert (
        logs[0]["to_state"]
        == "planned"
    )

    assert (
        logs[0]["actor_username"]
        == "statedoctor"
    )


def test_check_in_and_ready_keep_clinical_planned(
    client,
):
    session = (
        create_treatment_with_session(
            client
        )
    )

    check_in_response = transition(
        client,
        session["id"],
        "checked_in",
    )

    assert (
        check_in_response.status_code
        == 200
    )

    check_in_data = (
        check_in_response.json()
    )

    assert (
        check_in_data[
            "operational_status"
        ]
        == "checked_in"
    )

    assert (
        check_in_data["status"]
        == "planned"
    )

    ready_response = transition(
        client,
        session["id"],
        "ready",
    )

    assert (
        ready_response.status_code
        == 200
    )

    ready_data = ready_response.json()

    assert (
        ready_data[
            "operational_status"
        ]
        == "ready"
    )

    assert (
        ready_data["status"]
        == "planned"
    )


def test_start_treatment_updates_clinical_status(
    client,
):
    session = (
        create_treatment_with_session(
            client
        )
    )

    transition(
        client,
        session["id"],
        "checked_in",
    )

    transition(
        client,
        session["id"],
        "ready",
    )

    response = transition(
        client,
        session["id"],
        "in_treatment",
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["operational_status"]
        == "in_treatment"
    )

    assert (
        data["status"]
        == "in_progress"
    )

    assert (
        data["started_at"]
        is not None
    )


def test_complete_updates_clinical_status(
    client,
):
    session = (
        create_treatment_with_session(
            client
        )
    )

    for operational_status in (
        "checked_in",
        "ready",
        "in_treatment",
    ):
        response = transition(
            client,
            session["id"],
            operational_status,
        )

        assert (
            response.status_code
            == 200
        )

    response = transition(
        client,
        session["id"],
        "completed",
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["operational_status"]
        == "completed"
    )

    assert (
        data["status"]
        == "completed"
    )

    assert (
        data["completed_at"]
        is not None
    )


def test_scheduled_to_cancelled_is_allowed(
    client,
):
    session = (
        create_treatment_with_session(
            client
        )
    )

    response = transition(
        client,
        session["id"],
        "cancelled",
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["operational_status"]
        == "cancelled"
    )

    assert (
        data["status"]
        == "cancelled"
    )


def test_scheduled_to_completed_is_rejected(
    client,
):
    session = (
        create_treatment_with_session(
            client
        )
    )

    response = transition(
        client,
        session["id"],
        "completed",
    )

    assert response.status_code == 409


def test_cancelled_to_completed_is_rejected(
    client,
):
    session = (
        create_treatment_with_session(
            client
        )
    )

    cancel_response = transition(
        client,
        session["id"],
        "cancelled",
    )

    assert (
        cancel_response.status_code
        == 200
    )

    response = transition(
        client,
        session["id"],
        "completed",
    )

    assert response.status_code == 409


def test_workflow_transitions_are_audited(
    client,
):
    session = (
        create_treatment_with_session(
            client
        )
    )

    for operational_status in (
        "checked_in",
        "ready",
        "in_treatment",
        "completed",
    ):
        response = transition(
            client,
            session["id"],
            operational_status,
        )

        assert (
            response.status_code
            == 200
        )

    audit_response = client.get(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}/audit-logs"
        )
    )

    assert (
        audit_response.status_code
        == 200
    )

    logs = audit_response.json()

    assert len(logs) == 7

    assert (
        logs[0]["event_type"]
        == "session_created"
    )

    operational_logs = [
        log
        for log in logs
        if (
            log["event_type"]
            == "operational_transition"
        )
    ]

    clinical_logs = [
        log
        for log in logs
        if (
            log["event_type"]
            == "state_transition"
        )
    ]

    assert len(
        operational_logs
    ) == 4

    assert len(
        clinical_logs
    ) == 2

    assert (
        clinical_logs[0][
            "from_state"
        ]
        == "planned"
    )

    assert (
        clinical_logs[0][
            "to_state"
        ]
        == "in_progress"
    )

    assert (
        clinical_logs[1][
            "from_state"
        ]
        == "in_progress"
    )

    assert (
        clinical_logs[1][
            "to_state"
        ]
        == "completed"
    )

    assert all(
        log["actor_username"]
        == "statedoctor"
        for log in logs
    )