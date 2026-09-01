from backend.app.models.treatment_session_component import (
    TreatmentSessionComponent,
)


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
                f"COMP-SAFE-{suffix}"
            ),
            "first_name": "Completion",
            "last_name": "Safety",
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


def create_plan(
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
    admin_headers,
    *,
    treatment_id: str,
) -> dict:
    response = client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment_id}/sessions"
        ),
        headers=admin_headers,
        json={
            "session_number": 1,
            "body_region": "Knee",
        },
    )

    assert response.status_code == 201

    return response.json()


def administer(
    client,
    admin_headers,
    *,
    session_id: str,
    material_id: str,
    amount: str,
    plan_id: str | None = None,
    lot_number: str | None = None,
):
    move_to_in_treatment(
        client,
        admin_headers,
        session_id,
    )

    payload = {
        "material_id": material_id,
        "actual_amount": amount,
    }

    if plan_id is not None:
        payload[
            "treatment_component_id"
        ] = plan_id

    if lot_number is not None:
        payload["lot_number"] = lot_number

    return client.post(
        (
            "/api/v1/treatment-sessions/"
            f"{session_id}/components"
        ),
        headers=admin_headers,
        json=payload,
    )


def transition(
    client,
    headers,
    session_id: str,
    operational_status: str,
):
    return client.patch(
        (
            "/api/v1/treatment-sessions/"
            f"{session_id}/workflow"
        ),
        headers=headers,
        json={
            "operational_status": (
                operational_status
            ),
        },
    )


def move_to_in_treatment(
    client,
    headers,
    session_id: str,
):
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

    transitions = {
        "scheduled": "checked_in",
        "checked_in": "ready",
        "ready": "in_treatment",
    }

    while current not in {
        "in_treatment",
        "completed",
        "discharged",
        "cancelled",
    }:
        target = transitions.get(
            current
        )

        assert target is not None

        response = transition(
            client,
            headers,
            session_id,
            target,
        )

        assert response.status_code == 200

        data = response.json()

        current = data[
            "operational_status"
        ]

    return data

def completion_check(
    client,
    headers,
    session_id: str,
):
    return client.get(
        (
            "/api/v1/treatment-sessions/"
            f"{session_id}/completion-check"
        ),
        headers=headers,
    )


def test_no_plan_remains_completion_ready(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = completion_check(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["can_complete"] is True
    assert data["readiness"] == "ready"
    assert data["blocker_count"] == 0


def test_plan_without_actual_is_blocked(
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

    create_plan(
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

    response = completion_check(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["can_complete"] is False
    assert data["readiness"] == "blocked"
    assert data["blocker_count"] == 1

    blocker_codes = {
        issue["code"]
        for issue in data["issues"]
        if issue["severity"] == "blocker"
    }

    assert (
        "NO_ADMINISTRATION_RECORDED"
        in blocker_codes
    )


def test_workflow_cannot_complete_without_actual(
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

    create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=material["id"],
        amount="2.0",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    move_to_in_treatment(
        client,
        admin_headers,
        session["id"],
    )

    response = transition(
        client,
        admin_headers,
        session["id"],
        "completed",
    )

    assert response.status_code == 409

    response = client.get(
        (
            "/api/v1/treatment-sessions/"
            f"{session['id']}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "in_progress"

    assert (
        data["operational_status"]
        == "in_treatment"
    )


def test_aligned_session_can_complete(
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

    plan = create_plan(
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

    response = administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        amount="3.0",
        plan_id=plan["id"],
    )

    assert response.status_code == 201

    move_to_in_treatment(
        client,
        admin_headers,
        session["id"],
    )

    response = completion_check(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200
    assert response.json()["readiness"] == "ready"

    response = transition(
        client,
        admin_headers,
        session["id"],
        "completed",
    )

    assert response.status_code == 200

    assert response.json()["status"] == "completed"


def test_variance_warning_does_not_block_completion(
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

    plan = create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=material["id"],
        amount="2.0",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        amount="1.5",
        plan_id=plan["id"],
    )

    assert response.status_code == 201

    move_to_in_treatment(
        client,
        admin_headers,
        session["id"],
    )

    response = completion_check(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["can_complete"] is True

    assert (
        data["readiness"]
        == "ready_with_warnings"
    )

    warning_codes = {
        issue["code"]
        for issue in data["issues"]
        if issue["severity"] == "warning"
    }

    assert "UNDER_ADMINISTERED" in warning_codes

    response = transition(
        client,
        admin_headers,
        session["id"],
        "completed",
    )

    assert response.status_code == 200


def test_unplanned_administration_is_warning_only(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
    )

    planned_material = create_material(
        client,
        admin_headers,
        code="ACS",
        name="Autologous Conditioned Serum",
    )

    extra_material = create_material(
        client,
        admin_headers,
        code="HA",
        name="Hyaluronic Acid",
    )

    plan = create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=planned_material["id"],
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=planned_material["id"],
        amount="3.0",
        plan_id=plan["id"],
    )

    assert response.status_code == 201

    response = administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=extra_material["id"],
        amount="1.0",
    )

    assert response.status_code == 201

    move_to_in_treatment(
        client,
        admin_headers,
        session["id"],
    )

    response = completion_check(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["can_complete"] is True

    assert (
        data["readiness"]
        == "ready_with_warnings"
    )

    codes = {
        issue["code"]
        for issue in data["issues"]
    }

    assert (
        "UNPLANNED_ADMINISTRATION"
        in codes
    )


def test_legacy_missing_traceability_blocks_completion(
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
        code="EXOSOME",
        name="Exosome",
        unit="vial",
        requires_lot_tracking=True,
    )

    plan = create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=material["id"],
        amount="1.0",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    legacy_component = (
        TreatmentSessionComponent(
            treatment_session_id=session["id"],
            treatment_component_id=plan["id"],
            material_id=material["id"],
            actual_amount=1,
            unit="vial",
            sequence=1,
            lot_number=None,
            batch_number=None,
        )
    )

    db_session.add(
        legacy_component
    )
    db_session.commit()

    move_to_in_treatment(
        client,
        admin_headers,
        session["id"],
    )

    response = completion_check(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["can_complete"] is False
    assert data["readiness"] == "blocked"

    blocker_codes = {
        issue["code"]
        for issue in data["issues"]
        if issue["severity"] == "blocker"
    }

    assert "TRACEABILITY_MISSING" in blocker_codes

    response = transition(
        client,
        admin_headers,
        session["id"],
        "completed",
    )

    assert response.status_code == 409


def test_valid_lot_tracking_allows_completion(
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

    plan = create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=material["id"],
        amount="1.0",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        amount="1.0",
        plan_id=plan["id"],
        lot_number="EX-LOT-001",
    )

    assert response.status_code == 201

    move_to_in_treatment(
        client,
        admin_headers,
        session["id"],
    )

    response = completion_check(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["can_complete"] is True
    assert data["blocker_count"] == 0

    response = transition(
        client,
        admin_headers,
        session["id"],
        "completed",
    )

    assert response.status_code == 200


def test_missing_session_completion_check_returns_404(
    client,
    admin_headers,
):
    response = completion_check(
        client,
        admin_headers,
        "missing-session-id",
    )

    assert response.status_code == 404
