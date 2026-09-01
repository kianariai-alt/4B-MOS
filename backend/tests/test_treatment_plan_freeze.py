def create_treatment(
    client,
    admin_headers,
    *,
    suffix: str,
) -> dict:
    response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": (
                f"PLAN-FREEZE-{suffix}"
            ),
            "first_name": "Plan",
            "last_name": "Freeze",
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
) -> dict:
    response = client.post(
        "/api/v1/orthobiologic-materials",
        headers=admin_headers,
        json={
            "code": code,
            "name": name,
            "default_unit": "ml",
            "is_autologous": True,
            "requires_lot_tracking": False,
        },
    )

    assert response.status_code == 201

    return response.json()


def add_plan_component(
    client,
    admin_headers,
    *,
    treatment_id: str,
    material_id: str,
    amount: str = "3.0",
):
    return client.post(
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


def transition(
    client,
    admin_headers,
    *,
    session_id: str,
    target: str,
):
    return client.patch(
        (
            "/api/v1/treatment-sessions/"
            f"{session_id}/workflow"
        ),
        headers=admin_headers,
        json={
            "operational_status": target,
        },
    )


def move_to_ready(
    client,
    admin_headers,
    *,
    session_id: str,
) -> None:
    for target in (
        "checked_in",
        "ready",
    ):
        response = transition(
            client,
            admin_headers,
            session_id=session_id,
            target=target,
        )

        assert response.status_code == 200


def start_treatment(
    client,
    admin_headers,
    *,
    session_id: str,
) -> None:
    move_to_ready(
        client,
        admin_headers,
        session_id=session_id,
    )

    response = transition(
        client,
        admin_headers,
        session_id=session_id,
        target="in_treatment",
    )

    assert response.status_code == 200

    assert (
        response.json()["started_at"]
        is not None
    )


def test_plan_remains_mutable_before_execution(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix="BEFORE",
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

    response = add_plan_component(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=acs["id"],
    )

    assert response.status_code == 201

    acs_plan = response.json()

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    move_to_ready(
        client,
        admin_headers,
        session_id=session["id"],
    )

    response = client.patch(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{acs_plan['id']}"
        ),
        headers=admin_headers,
        json={
            "planned_amount": "4.0",
        },
    )

    assert response.status_code == 200

    response = add_plan_component(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=prgf["id"],
        amount="2.0",
    )

    assert response.status_code == 201

    prgf_plan = response.json()

    response = client.delete(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{prgf_plan['id']}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 204


def test_plan_is_frozen_after_execution_starts(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix="STARTED",
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

    pl = create_material(
        client,
        admin_headers,
        code="PL",
        name="Platelet Lysate",
    )

    response = add_plan_component(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=acs["id"],
    )

    assert response.status_code == 201
    acs_plan = response.json()

    response = add_plan_component(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=prgf["id"],
        amount="2.0",
    )

    assert response.status_code == 201
    prgf_plan = response.json()

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    start_treatment(
        client,
        admin_headers,
        session_id=session["id"],
    )

    response = add_plan_component(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=pl["id"],
        amount="1.0",
    )

    assert response.status_code == 409

    response = client.patch(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{acs_plan['id']}"
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
            f"{prgf_plan['id']}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 409


def test_cancellation_before_start_does_not_freeze_plan(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix="CANCEL-BEFORE",
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

    response = transition(
        client,
        admin_headers,
        session_id=session["id"],
        target="cancelled",
    )

    assert response.status_code == 200

    assert (
        response.json()["started_at"]
        is None
    )

    response = add_plan_component(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=material["id"],
    )

    assert response.status_code == 201


def test_cancellation_after_start_keeps_plan_frozen(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix="CANCEL-AFTER",
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

    response = add_plan_component(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=acs["id"],
    )

    assert response.status_code == 201

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    start_treatment(
        client,
        admin_headers,
        session_id=session["id"],
    )

    response = transition(
        client,
        admin_headers,
        session_id=session["id"],
        target="cancelled",
    )

    assert response.status_code == 200

    assert (
        response.json()["started_at"]
        is not None
    )

    response = add_plan_component(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=prgf["id"],
        amount="2.0",
    )

    assert response.status_code == 409
