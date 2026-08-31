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


def create_patient(
    client,
    admin_headers,
) -> dict:
    response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "RBAC-001",
            "first_name": "Clinical",
            "last_name": "Patient",
        },
    )

    assert response.status_code == 201

    return response.json()


def test_patient_requires_authentication(
    client,
):
    response = client.get(
        "/api/v1/patients"
    )

    assert response.status_code == 401


def test_viewer_can_read_patient(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    headers = login_role(
        client,
        admin_headers,
        username="viewer_patient",
        role="viewer",
    )

    response = client.get(
        f"/api/v1/patients/{patient['id']}",
        headers=headers,
    )

    assert response.status_code == 200


def test_viewer_cannot_create_patient(
    client,
    admin_headers,
):
    headers = login_role(
        client,
        admin_headers,
        username="viewer_create",
        role="viewer",
    )

    response = client.post(
        "/api/v1/patients",
        headers=headers,
        json={
            "patient_code": "VIEW-001",
            "first_name": "Blocked",
            "last_name": "Viewer",
        },
    )

    assert response.status_code == 403


def test_operator_can_create_patient(
    client,
    admin_headers,
):
    headers = login_role(
        client,
        admin_headers,
        username="operator_patient",
        role="operator",
    )

    response = client.post(
        "/api/v1/patients",
        headers=headers,
        json={
            "patient_code": "OP-001",
            "first_name": "Operator",
            "last_name": "Patient",
        },
    )

    assert response.status_code == 201


def test_operator_can_create_visit(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    headers = login_role(
        client,
        admin_headers,
        username="operator_visit",
        role="operator",
    )

    response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        headers=headers,
        json={
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201


def test_operator_cannot_update_visit(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    headers = login_role(
        client,
        admin_headers,
        username="operator_update",
        role="operator",
    )

    create_response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        headers=headers,
        json={
            "body_region": "Knee",
        },
    )

    assert create_response.status_code == 201

    visit_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/visits/{visit_id}",
        headers=headers,
        json={
            "notes": "Forbidden clinical edit",
        },
    )

    assert response.status_code == 403


def test_nurse_can_update_visit(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    headers = login_role(
        client,
        admin_headers,
        username="nurse_visit",
        role="nurse",
    )

    create_response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        headers=headers,
        json={
            "body_region": "Knee",
        },
    )

    assert create_response.status_code == 201

    visit_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/visits/{visit_id}",
        headers=headers,
        json={
            "notes": "Nursing follow-up.",
        },
    )

    assert response.status_code == 200