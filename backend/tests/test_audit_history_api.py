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
            "patient_code": "AUD-API-001",
            "first_name": "Audit",
            "last_name": "API",
        },
    )

    assert response.status_code == 201

    return response.json()


def create_visit(
    client,
    admin_headers,
) -> dict:
    patient = create_patient(
        client,
        admin_headers,
    )

    response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
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
) -> dict:
    visit = create_visit(
        client,
        admin_headers,
    )

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=admin_headers,
        json={
            "treatment_type": "PRP",
        },
    )

    assert response.status_code == 201

    return response.json()


def test_patient_audit_requires_authentication(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    response = client.get(
        f"/api/v1/patients/{patient['id']}/audit-logs"
    )

    assert response.status_code == 401


def test_viewer_cannot_read_audit_history(
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
            username="auditviewer",
            role="viewer",
        )
    )

    response = client.get(
        f"/api/v1/patients/{patient['id']}/audit-logs",
        headers=viewer_headers,
    )

    assert response.status_code == 403


def test_nurse_can_read_patient_audit(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    nurse_headers = (
        create_user_and_login(
            client,
            admin_headers,
            username="auditnurse",
            role="nurse",
        )
    )

    response = client.get(
        f"/api/v1/patients/{patient['id']}/audit-logs",
        headers=nurse_headers,
    )

    assert response.status_code == 200

    logs = response.json()

    assert len(logs) == 1

    assert (
        logs[0]["event_type"]
        == "patient_created"
    )


def test_admin_can_read_visit_audit(
    client,
    admin_headers,
):
    visit = create_visit(
        client,
        admin_headers,
    )

    response = client.get(
        f"/api/v1/visits/{visit['id']}/audit-logs",
        headers=admin_headers,
    )

    assert response.status_code == 200

    logs = response.json()

    assert len(logs) == 1

    assert (
        logs[0]["event_type"]
        == "visit_created"
    )


def test_physician_can_read_treatment_audit(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    physician_headers = (
        create_user_and_login(
            client,
            admin_headers,
            username="auditdoctorapi",
            role="physician",
        )
    )

    response = client.get(
        f"/api/v1/treatments/{treatment['id']}/audit-logs",
        headers=physician_headers,
    )

    assert response.status_code == 200

    logs = response.json()

    assert len(logs) == 1

    assert (
        logs[0]["event_type"]
        == "treatment_created"
    )


def test_admin_can_read_protocol_audit(
    client,
    admin_headers,
):
    create_response = client.post(
        "/api/v1/protocols",
        headers=admin_headers,
        json={
            "code": "AUD-API-PROT-001",
            "name": "Audit API Protocol",
            "treatment_type": "ACS",
            "version": "1.0",
        },
    )

    assert create_response.status_code == 201

    protocol = create_response.json()

    response = client.get(
        f"/api/v1/protocols/{protocol['id']}/audit-logs",
        headers=admin_headers,
    )

    assert response.status_code == 200

    logs = response.json()

    assert len(logs) == 1

    assert (
        logs[0]["event_type"]
        == "protocol_created"
    )


def test_missing_audit_entity_returns_404(
    client,
    admin_headers,
):
    response = client.get(
        "/api/v1/patients/not-real/audit-logs",
        headers=admin_headers,
    )

    assert response.status_code == 404


def test_audit_history_is_chronological(
    client,
    admin_headers,
):
    patient = create_patient(
        client,
        admin_headers,
    )

    update_response = client.patch(
        f"/api/v1/patients/{patient['id']}",
        headers=admin_headers,
        json={
            "first_name": "Updated",
        },
    )

    assert update_response.status_code == 200

    response = client.get(
        f"/api/v1/patients/{patient['id']}/audit-logs",
        headers=admin_headers,
    )

    assert response.status_code == 200

    logs = response.json()

    assert len(logs) == 2

    assert (
        logs[0]["event_type"]
        == "patient_created"
    )

    assert (
        logs[1]["event_type"]
        == "patient_updated"
    )