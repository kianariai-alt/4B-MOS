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
    *,
    suffix: str = "001",
) -> dict:
    response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": (
                f"SESSION-COMP-{suffix}"
            ),
            "first_name": "Session",
            "last_name": "Component",
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
    requires_lot_tracking: bool = False,
) -> dict:
    response = client.post(
        "/api/v1/orthobiologic-materials",
        headers=admin_headers,
        json={
            "code": code,
            "name": name,
            "default_unit": unit,
            "is_autologous": (
                not requires_lot_tracking
            ),
            "requires_lot_tracking": (
                requires_lot_tracking
            ),
        },
    )

    assert response.status_code == 201

    return response.json()


def create_planned_component(
    client,
    admin_headers,
    *,
    treatment_id: str,
    material_id: str,
    amount: str = "3.0",
) -> dict:
    response = client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment_id}/components"
        ),
        headers=admin_headers,
        json={
            "material_id": material_id,
            "planned_amount": amount,
        },
    )

    assert response.status_code == 201

    return response.json()


def create_session(
    client,
    headers,
    *,
    treatment_id: str,
    session_number: int = 1,
) -> dict:
    response = client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment_id}/sessions"
        ),
        headers=headers,
        json={
            "session_number": session_number,
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201

    return response.json()


def ensure_in_treatment(
    client,
    headers,
    session_id: str,
) -> dict:
    response = client.get(
        (
            "/api/v1/treatment-sessions/"
            f"{session_id}"
        ),
        headers=headers,
    )

    assert response.status_code == 200

    data = response.json()

    current = data[
        "operational_status"
    ]

    if current in {
        "in_treatment",
        "completed",
        "discharged",
        "cancelled",
    }:
        return data

    transitions = {
        "scheduled": "checked_in",
        "checked_in": "ready",
        "ready": "in_treatment",
    }

    while current != "in_treatment":
        target = transitions.get(
            current
        )

        if target is None:
            raise AssertionError(
                "Session cannot be moved "
                "to in_treatment from "
                f"'{current}'."
            )

        response = client.patch(
            (
                "/api/v1/treatment-sessions/"
                f"{session_id}/workflow"
            ),
            headers=headers,
            json={
                "operational_status": target,
            },
        )

        assert response.status_code == 200

        data = response.json()

        current = data[
            "operational_status"
        ]

    return data


def add_actual_component(
    client,
    headers,
    *,
    session_id: str,
    material_id: str,
    actual_amount: str = "3.0",
    treatment_component_id: str | None = None,
    sequence: int | None = None,
    lot_number: str | None = None,
    batch_number: str | None = None,
):
    ensure_in_treatment(
        client,
        headers,
        session_id,
    )

    payload = {
        "material_id": material_id,
        "actual_amount": actual_amount,
    }

    if treatment_component_id is not None:
        payload[
            "treatment_component_id"
        ] = treatment_component_id

    if sequence is not None:
        payload["sequence"] = sequence

    if lot_number is not None:
        payload["lot_number"] = lot_number

    if batch_number is not None:
        payload["batch_number"] = batch_number

    return client.post(
        (
            "/api/v1/treatment-sessions/"
            f"{session_id}/components"
        ),
        headers=headers,
        json=payload,
    )


def complete_session(
    client,
    headers,
    session_id: str,
) -> dict:
    data = ensure_in_treatment(
        client,
        headers,
        session_id,
    )

    if (
        data["operational_status"]
        == "completed"
    ):
        return data

    response = client.patch(
        (
            "/api/v1/treatment-sessions/"
            f"{session_id}/workflow"
        ),
        headers=headers,
        json={
            "operational_status": (
                "completed"
            ),
        },
    )

    assert response.status_code == 200

    return response.json()

def test_linked_planned_component_is_recorded(
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

    planned = create_planned_component(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=material["id"],
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        actual_amount="3.2",
        treatment_component_id=planned["id"],
    )

    assert response.status_code == 201

    data = response.json()

    assert (
        data["treatment_component_id"]
        == planned["id"]
    )
    assert data["material"]["code"] == "ACS"
    assert data["actual_amount"] == "3.2000"
    assert data["unit"] == "ml"
    assert data["sequence"] == 1


def test_lot_tracking_is_required(
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
        code="EXOSOME",
        name="Exosome",
        unit="vial",
        requires_lot_tracking=True,
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        actual_amount="1",
    )

    assert response.status_code == 409

    response = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        actual_amount="1",
        lot_number="EX-2026-001",
    )

    assert response.status_code == 201
    assert (
        response.json()["lot_number"]
        == "EX-2026-001"
    )


def test_planned_component_from_other_treatment_is_rejected(
    client,
    admin_headers,
):
    treatment_a = create_treatment(
        client,
        admin_headers,
        suffix="A",
    )

    treatment_b = create_treatment(
        client,
        admin_headers,
        suffix="B",
    )

    material = create_material(
        client,
        admin_headers,
        code="ACS",
        name="Autologous Conditioned Serum",
    )

    planned = create_planned_component(
        client,
        admin_headers,
        treatment_id=treatment_a["id"],
        material_id=material["id"],
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment_b["id"],
    )

    response = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        treatment_component_id=planned["id"],
    )

    assert response.status_code == 409


def test_planned_material_mismatch_is_rejected(
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

    planned = create_planned_component(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=acs["id"],
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=prgf["id"],
        treatment_component_id=planned["id"],
    )

    assert response.status_code == 409


def test_unplanned_administration_is_allowed(
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

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        actual_amount="2.0",
    )

    assert response.status_code == 201

    data = response.json()

    assert (
        data["treatment_component_id"]
        is None
    )
    assert data["material"]["code"] == "PRGF"


def test_same_material_can_use_multiple_lots(
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
        code="EXOSOME",
        name="Exosome",
        unit="vial",
        requires_lot_tracking=True,
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    first = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        actual_amount="1",
        lot_number="LOT-A",
    )

    second = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        actual_amount="1",
        lot_number="LOT-B",
    )

    assert first.status_code == 201
    assert second.status_code == 201

    assert first.json()["sequence"] == 1
    assert second.json()["sequence"] == 2


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

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    first = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=acs["id"],
        sequence=1,
    )

    second = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=prgf["id"],
        sequence=1,
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_operator_can_write_and_viewer_can_only_read(
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

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    operator_headers = create_user_and_login(
        client,
        admin_headers,
        username="sessionoperator",
        role="operator",
    )

    response = add_actual_component(
        client,
        operator_headers,
        session_id=session["id"],
        material_id=material["id"],
    )

    assert response.status_code == 201

    viewer_headers = create_user_and_login(
        client,
        admin_headers,
        username="sessionviewer",
        role="viewer",
    )

    response = client.get(
        (
            "/api/v1/treatment-sessions/"
            f"{session['id']}/components"
        ),
        headers=viewer_headers,
    )

    assert response.status_code == 200
    assert len(response.json()) == 1

    response = add_actual_component(
        client,
        viewer_headers,
        session_id=session["id"],
        material_id=material["id"],
    )

    assert response.status_code == 403


def test_traceability_cannot_be_removed(
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
        code="EXOSOME",
        name="Exosome",
        unit="vial",
        requires_lot_tracking=True,
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        actual_amount="1",
        lot_number="TRACE-001",
    )

    assert response.status_code == 201

    component = response.json()

    response = client.patch(
        (
            "/api/v1/treatment-sessions/"
            f"{session['id']}/components/"
            f"{component['id']}"
        ),
        headers=admin_headers,
        json={
            "lot_number": None,
            "batch_number": None,
        },
    )

    assert response.status_code == 409


def test_components_lock_after_session_completion(
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

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
    )

    assert response.status_code == 201

    component = response.json()

    completed = complete_session(
        client,
        admin_headers,
        session["id"],
    )

    assert completed["status"] == "completed"

    response = client.patch(
        (
            "/api/v1/treatment-sessions/"
            f"{session['id']}/components/"
            f"{component['id']}"
        ),
        headers=admin_headers,
        json={
            "actual_amount": "4.0",
        },
    )

    assert response.status_code == 409

    response = client.delete(
        (
            "/api/v1/treatment-sessions/"
            f"{session['id']}/components/"
            f"{component['id']}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 409

    response = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
    )

    assert response.status_code == 409


def test_session_component_lifecycle_is_audited(
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

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = add_actual_component(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        actual_amount="2.0",
    )

    assert response.status_code == 201

    component = response.json()

    response = client.patch(
        (
            "/api/v1/treatment-sessions/"
            f"{session['id']}/components/"
            f"{component['id']}"
        ),
        headers=admin_headers,
        json={
            "actual_amount": "2.5",
            "notes": "Adjusted administration",
        },
    )

    assert response.status_code == 200

    response = client.delete(
        (
            "/api/v1/treatment-sessions/"
            f"{session['id']}/components/"
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
            == "treatment_session_component",
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
        "session_component_created",
        "session_component_updated",
        "session_component_deleted",
    ]


def test_actual_administration_is_rejected_before_treatment_starts(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix="LIFECYCLE-PLANNED",
    )

    material = create_material(
        client,
        admin_headers,
        code="BMAC",
        name="Bone Marrow Aspirate Concentrate",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = client.post(
        (
            "/api/v1/treatment-sessions/"
            f"{session['id']}/components"
        ),
        headers=admin_headers,
        json={
            "material_id": material["id"],
            "actual_amount": "2.0",
        },
    )

    assert response.status_code == 409

    session_response = client.get(
        (
            "/api/v1/treatment-sessions/"
            f"{session['id']}"
        ),
        headers=admin_headers,
    )

    assert session_response.status_code == 200

    assert (
        session_response.json()["status"]
        == "planned"
    )


def test_actual_amount_is_required(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix="AMOUNT-REQUIRED",
    )

    material = create_material(
        client,
        admin_headers,
        code="SVF",
        name="Stromal Vascular Fraction",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    ensure_in_treatment(
        client,
        admin_headers,
        session["id"],
    )

    response = client.post(
        (
            "/api/v1/treatment-sessions/"
            f"{session['id']}/components"
        ),
        headers=admin_headers,
        json={
            "material_id": material["id"],
        },
    )

    assert response.status_code == 422
