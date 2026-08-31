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


def create_visit_as_admin(
    client,
    admin_headers,
) -> dict:
    patient_response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "TP-RBAC-001",
            "first_name": "Treatment",
            "last_name": "RBAC",
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

    return visit_response.json()


def create_treatment_as_admin(
    client,
    admin_headers,
) -> dict:
    visit = create_visit_as_admin(
        client,
        admin_headers,
    )

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=admin_headers,
        json={
            "treatment_type": "PRP",
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201

    return response.json()


def create_protocol_as_admin(
    client,
    admin_headers,
) -> dict:
    response = client.post(
        "/api/v1/protocols",
        headers=admin_headers,
        json={
            "code": "RBAC-PRP-001",
            "name": "RBAC PRP Protocol",
            "treatment_type": "PRP",
            "version": "1.0",
        },
    )

    assert response.status_code == 201

    return response.json()


def test_treatment_requires_authentication(
    client,
    admin_headers,
):
    treatment = create_treatment_as_admin(
        client,
        admin_headers,
    )

    response = client.get(
        f"/api/v1/treatments/{treatment['id']}"
    )

    assert response.status_code == 401


def test_viewer_can_read_treatment(
    client,
    admin_headers,
):
    treatment = create_treatment_as_admin(
        client,
        admin_headers,
    )

    headers = login_role(
        client,
        admin_headers,
        username="viewer_treatment",
        role="viewer",
    )

    response = client.get(
        f"/api/v1/treatments/{treatment['id']}",
        headers=headers,
    )

    assert response.status_code == 200


def test_operator_cannot_create_treatment(
    client,
    admin_headers,
):
    visit = create_visit_as_admin(
        client,
        admin_headers,
    )

    headers = login_role(
        client,
        admin_headers,
        username="operator_treatment",
        role="operator",
    )

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=headers,
        json={
            "treatment_type": "PRP",
        },
    )

    assert response.status_code == 403


def test_nurse_cannot_update_treatment(
    client,
    admin_headers,
):
    treatment = create_treatment_as_admin(
        client,
        admin_headers,
    )

    headers = login_role(
        client,
        admin_headers,
        username="nurse_treatment",
        role="nurse",
    )

    response = client.patch(
        f"/api/v1/treatments/{treatment['id']}",
        headers=headers,
        json={
            "notes": "Blocked update",
        },
    )

    assert response.status_code == 403


def test_physician_can_create_treatment(
    client,
    admin_headers,
):
    visit = create_visit_as_admin(
        client,
        admin_headers,
    )

    headers = login_role(
        client,
        admin_headers,
        username="physician_treatment",
        role="physician",
    )

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=headers,
        json={
            "treatment_type": "ACS",
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201


def test_protocol_requires_authentication(
    client,
):
    response = client.get(
        "/api/v1/protocols"
    )

    assert response.status_code == 401


def test_viewer_can_read_protocol(
    client,
    admin_headers,
):
    protocol = create_protocol_as_admin(
        client,
        admin_headers,
    )

    headers = login_role(
        client,
        admin_headers,
        username="viewer_protocol",
        role="viewer",
    )

    response = client.get(
        f"/api/v1/protocols/{protocol['id']}",
        headers=headers,
    )

    assert response.status_code == 200


def test_operator_cannot_create_protocol(
    client,
    admin_headers,
):
    headers = login_role(
        client,
        admin_headers,
        username="operator_protocol",
        role="operator",
    )

    response = client.post(
        "/api/v1/protocols",
        headers=headers,
        json={
            "code": "BLOCKED-001",
            "name": "Blocked Protocol",
            "treatment_type": "PRP",
            "version": "1.0",
        },
    )

    assert response.status_code == 403


def test_nurse_cannot_deactivate_protocol(
    client,
    admin_headers,
):
    protocol = create_protocol_as_admin(
        client,
        admin_headers,
    )

    headers = login_role(
        client,
        admin_headers,
        username="nurse_protocol",
        role="nurse",
    )

    response = client.delete(
        f"/api/v1/protocols/{protocol['id']}",
        headers=headers,
    )

    assert response.status_code == 403


def test_physician_can_create_protocol(
    client,
    admin_headers,
):
    headers = login_role(
        client,
        admin_headers,
        username="physician_protocol",
        role="physician",
    )

    response = client.post(
        "/api/v1/protocols",
        headers=headers,
        json={
            "code": "PHYS-PRP-001",
            "name": "Physician PRP Protocol",
            "treatment_type": "PRP",
            "version": "1.0",
        },
    )

    assert response.status_code == 201