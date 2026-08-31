def create_user_and_login(
    client,
    admin_headers,
    *,
    username: str,
    role: str,
) -> tuple[dict, dict]:
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

    user = create_response.json()

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

    headers = {
        "Authorization": f"Bearer {token}",
    }

    return user, headers


def create_treatment(
    client,
    admin_headers,
) -> dict:
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "RBAC-PAT-001",
            "first_name": "RBAC",
            "last_name": "Patient",
        },
    )

    assert patient_response.status_code == 201

    patient = patient_response.json()

    visit_response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        headers=admin_headers,
        json={
            "body_region": "Knee",
        },
    )

    assert visit_response.status_code == 201

    visit = visit_response.json()

    treatment_response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=admin_headers,
        json={
            "treatment_type": "PRP",
            "body_region": "Knee",
        },
    )

    assert treatment_response.status_code == 201

    return treatment_response.json()


def test_session_creation_requires_authentication(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
    )

    assert response.status_code == 401


def test_viewer_cannot_create_session(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    _, headers = create_user_and_login(
        client,
        admin_headers,
        username="viewer1",
        role="viewer",
    )

    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
        headers=headers,
    )

    assert response.status_code == 403


def test_physician_can_create_session_and_is_audited(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    user, headers = create_user_and_login(
        client,
        admin_headers,
        username="physician1",
        role="physician",
    )

    create_response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
        headers=headers,
    )

    assert create_response.status_code == 201

    session_id = create_response.json()[
        "id"
    ]

    audit_response = client.get(
        f"/api/v1/treatment-sessions/{session_id}/audit-logs",
        headers=headers,
    )

    assert audit_response.status_code == 200

    logs = audit_response.json()

    assert len(logs) == 1

    log = logs[0]

    assert (
        log["event_type"]
        == "session_created"
    )

    assert (
        log["actor_user_id"]
        == user["id"]
    )

    assert (
        log["actor_username"]
        == "physician1"
    )

    assert (
        log["actor_role"]
        == "physician"
    )


def test_viewer_can_read_existing_sessions(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    _, physician_headers = (
        create_user_and_login(
            client,
            admin_headers,
            username="physician2",
            role="physician",
        )
    )

    create_response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
        headers=physician_headers,
    )

    assert create_response.status_code == 201

    _, viewer_headers = (
        create_user_and_login(
            client,
            admin_headers,
            username="viewer2",
            role="viewer",
        )
    )

    response = client.get(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        headers=viewer_headers,
    )

    assert response.status_code == 200

    assert len(
        response.json()
    ) == 1


def test_operator_transition_is_recorded_in_audit(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    _, physician_headers = (
        create_user_and_login(
            client,
            admin_headers,
            username="physician3",
            role="physician",
        )
    )

    create_response = client.post(
        f"/api/v1/treatments/{treatment['id']}/sessions",
        json={
            "session_number": 1,
        },
        headers=physician_headers,
    )

    assert create_response.status_code == 201

    session_id = create_response.json()[
        "id"
    ]

    operator, operator_headers = (
        create_user_and_login(
            client,
            admin_headers,
            username="operator1",
            role="operator",
        )
    )

    update_response = client.patch(
        f"/api/v1/treatment-sessions/{session_id}",
        json={
            "status": "in_progress",
        },
        headers=operator_headers,
    )

    assert update_response.status_code == 200

    audit_response = client.get(
        f"/api/v1/treatment-sessions/{session_id}/audit-logs",
        headers=operator_headers,
    )

    assert audit_response.status_code == 200

    logs = audit_response.json()

    assert len(logs) == 2

    transition = logs[1]

    assert (
        transition["event_type"]
        == "state_transition"
    )

    assert (
        transition["from_state"]
        == "planned"
    )

    assert (
        transition["to_state"]
        == "in_progress"
    )

    assert (
        transition["actor_user_id"]
        == operator["id"]
    )

    assert (
        transition["actor_username"]
        == "operator1"
    )

    assert (
        transition["actor_role"]
        == "operator"
    )