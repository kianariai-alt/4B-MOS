from sqlalchemy import select

from backend.app.models.audit_log import (
    AuditLog,
)


def create_user_and_login(
    client,
    admin_headers,
    *,
    username: str,
    role: str,
) -> dict:
    response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": username,
            "display_name": username,
            "password": "StrongPass123",
            "role": role,
        },
    )

    assert response.status_code == 201

    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": "StrongPass123",
        },
    )

    assert response.status_code == 200

    return {
        "Authorization": (
            "Bearer "
            + response.json()["access_token"]
        ),
    }


def create_treatment(
    client,
    admin_headers,
) -> dict:
    response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": "COMBO-001",
            "first_name": "Combination",
            "last_name": "Patient",
        },
    )

    assert response.status_code == 201

    patient = response.json()

    response = client.post(
        (
            f"/api/v1/patients/"
            f"{patient['id']}/visits"
        ),
        headers=admin_headers,
        json={
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201

    visit = response.json()

    response = client.post(
        (
            f"/api/v1/visits/"
            f"{visit['id']}/treatments"
        ),
        headers=admin_headers,
        json={
            "treatment_type": "ACS",
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201

    return response.json()


def create_material(
    client,
    admin_headers,
    *,
    code: str,
    name: str,
    unit: str = "ml",
    is_autologous: bool = True,
) -> dict:
    response = client.post(
        "/api/v1/orthobiologic-materials",
        headers=admin_headers,
        json={
            "code": code,
            "name": name,
            "default_unit": unit,
            "is_autologous": is_autologous,
            "requires_lot_tracking": (
                not is_autologous
            ),
        },
    )

    assert response.status_code == 201

    return response.json()


def add_component(
    client,
    admin_headers,
    treatment_id: str,
    material_id: str,
    *,
    amount: str = "3.0",
    sequence: int | None = None,
):
    payload = {
        "material_id": material_id,
        "planned_amount": amount,
    }

    if sequence is not None:
        payload["sequence"] = sequence

    return client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment_id}/components"
        ),
        headers=admin_headers,
        json=payload,
    )


def test_add_component_uses_material_default_unit(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    material = create_material(
        client,
        admin_headers,
        code="ACS",
        name="Autologous Conditioned Serum",
    )

    response = add_component(
        client,
        admin_headers,
        treatment["id"],
        material["id"],
    )

    assert response.status_code == 201

    data = response.json()

    assert data["material"]["code"] == "ACS"
    assert data["planned_amount"] == "3.0000"
    assert data["unit"] == "ml"
    assert data["sequence"] == 1


def test_sequence_is_generated_automatically(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    acs = create_material(
        client,
        admin_headers,
        code="ACS",
        name="Autologous Conditioned Serum",
    )

    prgf = create_material(
        client,
        admin_headers,
        code="PRGF",
        name="Plasma Rich in Growth Factors",
    )

    first = add_component(
        client,
        admin_headers,
        treatment["id"],
        acs["id"],
    )

    second = add_component(
        client,
        admin_headers,
        treatment["id"],
        prgf["id"],
        amount="2.0",
    )

    assert first.status_code == 201
    assert second.status_code == 201

    assert first.json()["sequence"] == 1
    assert second.json()["sequence"] == 2


def test_duplicate_material_is_rejected(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    material = create_material(
        client,
        admin_headers,
        code="ACS",
        name="Autologous Conditioned Serum",
    )

    first = add_component(
        client,
        admin_headers,
        treatment["id"],
        material["id"],
    )

    duplicate = add_component(
        client,
        admin_headers,
        treatment["id"],
        material["id"],
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409


def test_duplicate_sequence_is_rejected(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    acs = create_material(
        client,
        admin_headers,
        code="ACS",
        name="Autologous Conditioned Serum",
    )

    prgf = create_material(
        client,
        admin_headers,
        code="PRGF",
        name="Plasma Rich in Growth Factors",
    )

    first = add_component(
        client,
        admin_headers,
        treatment["id"],
        acs["id"],
        sequence=1,
    )

    second = add_component(
        client,
        admin_headers,
        treatment["id"],
        prgf["id"],
        sequence=1,
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_inactive_material_is_rejected(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    material = create_material(
        client,
        admin_headers,
        code="PRGF",
        name="Plasma Rich in Growth Factors",
    )

    response = client.delete(
        (
            "/api/v1/"
            "orthobiologic-materials/"
            f"{material['id']}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    response = add_component(
        client,
        admin_headers,
        treatment["id"],
        material["id"],
    )

    assert response.status_code == 409


def test_viewer_can_read_components(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    material = create_material(
        client,
        admin_headers,
        code="ACS",
        name="Autologous Conditioned Serum",
    )

    response = add_component(
        client,
        admin_headers,
        treatment["id"],
        material["id"],
    )

    assert response.status_code == 201

    viewer_headers = create_user_and_login(
        client,
        admin_headers,
        username="comboviewer",
        role="viewer",
    )

    response = client.get(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components"
        ),
        headers=viewer_headers,
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_operator_cannot_modify_combination(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    material = create_material(
        client,
        admin_headers,
        code="ACS",
        name="Autologous Conditioned Serum",
    )

    operator_headers = create_user_and_login(
        client,
        admin_headers,
        username="combooperator",
        role="operator",
    )

    response = client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components"
        ),
        headers=operator_headers,
        json={
            "material_id": material["id"],
            "planned_amount": "3.0",
        },
    )

    assert response.status_code == 403


def test_component_can_be_updated_while_planned(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    material = create_material(
        client,
        admin_headers,
        code="ACS",
        name="Autologous Conditioned Serum",
    )

    response = add_component(
        client,
        admin_headers,
        treatment["id"],
        material["id"],
    )

    component = response.json()

    response = client.patch(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{component['id']}"
        ),
        headers=admin_headers,
        json={
            "planned_amount": "4.5",
            "unit": "ML",
            "sequence": 2,
            "notes": "Updated plan",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["planned_amount"] == "4.5000"
    assert data["unit"] == "ml"
    assert data["sequence"] == 2
    assert data["notes"] == "Updated plan"


def test_combination_is_locked_after_treatment_starts(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    acs = create_material(
        client,
        admin_headers,
        code="ACS",
        name="Autologous Conditioned Serum",
    )

    prgf = create_material(
        client,
        admin_headers,
        code="PRGF",
        name="Plasma Rich in Growth Factors",
    )

    response = add_component(
        client,
        admin_headers,
        treatment["id"],
        acs["id"],
    )

    assert response.status_code == 201

    component = response.json()

    response = client.patch(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}"
        ),
        headers=admin_headers,
        json={
            "status": "in_progress",
        },
    )

    assert response.status_code == 200

    response = add_component(
        client,
        admin_headers,
        treatment["id"],
        prgf["id"],
    )

    assert response.status_code == 409

    response = client.patch(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{component['id']}"
        ),
        headers=admin_headers,
        json={
            "planned_amount": "5.0",
        },
    )

    assert response.status_code == 409

    response = client.delete(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{component['id']}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 409


def test_component_lifecycle_is_audited(
    client,
    admin_headers,
    db_session,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    material = create_material(
        client,
        admin_headers,
        code="PRGF",
        name="Plasma Rich in Growth Factors",
    )

    response = add_component(
        client,
        admin_headers,
        treatment["id"],
        material["id"],
        amount="2.0",
    )

    assert response.status_code == 201

    component = response.json()

    response = client.patch(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{component['id']}"
        ),
        headers=admin_headers,
        json={
            "planned_amount": "2.5",
        },
    )

    assert response.status_code == 200

    response = client.delete(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{component['id']}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 204

    db_session.expire_all()

    statement = (
        select(AuditLog)
        .where(
            AuditLog.entity_type
            == "treatment_component",
            AuditLog.entity_id
            == component["id"],
        )
        .order_by(
            AuditLog.created_at.asc(),
            AuditLog.id.asc(),
        )
    )

    logs = list(
        db_session.scalars(statement).all()
    )

    assert len(logs) == 3

    assert [
        log.event_type
        for log in logs
    ] == [
        "treatment_component_created",
        "treatment_component_updated",
        "treatment_component_deleted",
    ]
