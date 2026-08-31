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
            "display_name": username.title(),
            "password": password,
            "role": role,
        },
    )

    assert create_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": password,
        },
    )

    assert login_response.status_code == 200

    token = login_response.json()[
        "access_token"
    ]

    return {
        "Authorization": f"Bearer {token}",
    }


def create_session(
    client,
    admin_headers,
) -> dict:
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "WORKFLOW-001",
            "first_name": "Workflow",
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


def transition(
    client,
    headers,
    session_id: str,
    operational_status: str,
):
    return client.patch(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session_id}/workflow"
        ),
        headers=headers,
        json={
            "operational_status": (
                operational_status
            ),
        },
    )


def test_workflow_requires_authentication(
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
            f"{session['id']}/workflow"
        ),
        json={
            "operational_status": (
                "checked_in"
            ),
        },
    )

    assert response.status_code == 401


def test_viewer_cannot_change_workflow(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    viewer_headers = login_role(
        client,
        admin_headers,
        username="workflowviewer",
        role="viewer",
    )

    response = transition(
        client,
        viewer_headers,
        session["id"],
        "checked_in",
    )

    assert response.status_code == 403


def test_new_session_is_scheduled(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    assert (
        session["operational_status"]
        == "scheduled"
    )

    assert session["checked_in_at"] is None


def test_check_in_sets_timestamp(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    response = transition(
        client,
        admin_headers,
        session["id"],
        "checked_in",
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["operational_status"]
        == "checked_in"
    )

    assert data["checked_in_at"] is not None
    assert data["status"] == "planned"


def test_invalid_operational_jump_returns_409(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    response = transition(
        client,
        admin_headers,
        session["id"],
        "ready",
    )

    assert response.status_code == 409


def test_ready_then_start_treatment(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    response = transition(
        client,
        admin_headers,
        session["id"],
        "checked_in",
    )

    assert response.status_code == 200

    response = transition(
        client,
        admin_headers,
        session["id"],
        "ready",
    )

    assert response.status_code == 200
    assert response.json()["ready_at"] is not None

    response = transition(
        client,
        admin_headers,
        session["id"],
        "in_treatment",
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["operational_status"]
        == "in_treatment"
    )

    assert data["status"] == "in_progress"
    assert data["started_at"] is not None


def test_complete_then_discharge(
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
        response = transition(
            client,
            admin_headers,
            session["id"],
            state,
        )

        assert response.status_code == 200

    completed = response.json()

    assert completed["status"] == "completed"

    assert (
        completed["completed_at"]
        is not None
    )

    response = transition(
        client,
        admin_headers,
        session["id"],
        "discharged",
    )

    assert response.status_code == 200

    discharged = response.json()

    assert (
        discharged["operational_status"]
        == "discharged"
    )

    assert (
        discharged["discharged_at"]
        is not None
    )


def test_operator_can_check_in_patient(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    operator_headers = login_role(
        client,
        admin_headers,
        username="workflowoperator",
        role="operator",
    )

    response = transition(
        client,
        operator_headers,
        session["id"],
        "checked_in",
    )

    assert response.status_code == 200

    assert (
        response.json()[
            "operational_status"
        ]
        == "checked_in"
    )


def test_operational_transition_is_audited(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    response = transition(
        client,
        admin_headers,
        session["id"],
        "checked_in",
    )

    assert response.status_code == 200

    audit_response = client.get(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}/audit-logs"
        ),
        headers=admin_headers,
    )

    assert audit_response.status_code == 200

    logs = audit_response.json()

    operational_logs = [
        log
        for log in logs
        if (
            log["event_type"]
            == "operational_transition"
        )
    ]

    assert len(operational_logs) == 1

    log = operational_logs[0]

    assert (
        log["from_state"]
        == "scheduled"
    )

    assert (
        log["to_state"]
        == "checked_in"
    )

    assert (
        log["actor_username"]
        == "testadmin"
    )


def test_workflow_cancellation(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    response = transition(
        client,
        admin_headers,
        session["id"],
        "cancelled",
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["operational_status"]
        == "cancelled"
    )

    assert data["status"] == "cancelled"