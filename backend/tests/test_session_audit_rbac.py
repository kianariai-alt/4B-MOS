def create_user_and_login(
    client,
    admin_headers,
    *,
    username: str,
    role: str,
) -> dict:
    create_response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": username,
            "display_name": username,
            "password": "StrongPass123",
            "role": role,
        },
    )

    assert create_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": "StrongPass123",
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
            "patient_code": "AUDIT-RBAC-001",
            "first_name": "Audit",
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


def test_nurse_can_read_session_audit(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    nurse_headers = create_user_and_login(
        client,
        admin_headers,
        username="auditnurse",
        role="nurse",
    )

    response = client.get(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}/audit-logs"
        ),
        headers=nurse_headers,
    )

    assert response.status_code == 200


def test_operator_cannot_read_session_audit(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    operator_headers = create_user_and_login(
        client,
        admin_headers,
        username="auditoperator",
        role="operator",
    )

    response = client.get(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}/audit-logs"
        ),
        headers=operator_headers,
    )

    assert response.status_code == 403


def test_viewer_cannot_read_session_audit(
    client,
    admin_headers,
):
    session = create_session(
        client,
        admin_headers,
    )

    viewer_headers = create_user_and_login(
        client,
        admin_headers,
        username="auditviewer",
        role="viewer",
    )

    response = client.get(
        (
            "/api/v1/"
            "treatment-sessions/"
            f"{session['id']}/audit-logs"
        ),
        headers=viewer_headers,
    )

    assert response.status_code == 403