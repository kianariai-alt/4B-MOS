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
                f"PLAN-REF-{suffix}"
            ),
            "first_name": "Plan",
            "last_name": "Reference",
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
) -> dict:
    response = client.post(
        "/api/v1/orthobiologic-materials",
        headers=admin_headers,
        json={
            "code": "ACS",
            "name": (
                "Autologous Conditioned Serum"
            ),
            "default_unit": "ml",
            "is_autologous": True,
            "requires_lot_tracking": False,
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
) -> dict:
    response = client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment_id}/components"
        ),
        headers=admin_headers,
        json={
            "material_id": material_id,
            "planned_amount": "3.0",
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


def start_session(
    client,
    admin_headers,
    session_id: str,
) -> None:
    for target in (
        "checked_in",
        "ready",
        "in_treatment",
    ):
        response = client.patch(
            (
                "/api/v1/treatment-sessions/"
                f"{session_id}/workflow"
            ),
            headers=admin_headers,
            json={
                "operational_status": target,
            },
        )

        assert response.status_code == 200


def record_actual(
    client,
    admin_headers,
    *,
    session_id: str,
    plan_id: str,
    material_id: str,
) -> dict:
    response = client.post(
        (
            "/api/v1/treatment-sessions/"
            f"{session_id}/components"
        ),
        headers=admin_headers,
        json={
            "treatment_component_id": (
                plan_id
            ),
            "material_id": material_id,
            "actual_amount": "3.0",
        },
    )

    assert response.status_code == 201

    return response.json()


def setup_referenced_plan(
    client,
    admin_headers,
    *,
    suffix: str,
):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix=suffix,
    )

    material = create_material(
        client,
        admin_headers,
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

    start_session(
        client,
        admin_headers,
        session["id"],
    )

    actual = record_actual(
        client,
        admin_headers,
        session_id=session["id"],
        plan_id=plan["id"],
        material_id=material["id"],
    )

    return (
        treatment,
        material,
        plan,
        session,
        actual,
    )


def test_referenced_plan_cannot_be_updated(
    client,
    admin_headers,
):
    (
        treatment,
        _material,
        plan,
        _session,
        _actual,
    ) = setup_referenced_plan(
        client,
        admin_headers,
        suffix="UPDATE",
    )

    response = client.patch(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{plan['id']}"
        ),
        headers=admin_headers,
        json={
            "planned_amount": "4.0",
        },
    )

    assert response.status_code == 409

    response = client.get(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{plan['id']}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    assert (
        response.json()["planned_amount"]
        == "3.0000"
    )


def test_referenced_plan_cannot_be_deleted(
    client,
    admin_headers,
):
    (
        treatment,
        _material,
        plan,
        session,
        actual,
    ) = setup_referenced_plan(
        client,
        admin_headers,
        suffix="DELETE",
    )

    response = client.delete(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{plan['id']}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 409

    response = client.get(
        (
            "/api/v1/treatment-sessions/"
            f"{session['id']}/components/"
            f"{actual['id']}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    assert (
        response.json()[
            "treatment_component_id"
        ]
        == plan["id"]
    )


def test_unreferenced_plan_remains_mutable(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix="FREE",
    )

    material = create_material(
        client,
        admin_headers,
    )

    plan = create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=material["id"],
    )

    response = client.patch(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{plan['id']}"
        ),
        headers=admin_headers,
        json={
            "planned_amount": "4.0",
        },
    )

    assert response.status_code == 200

    assert (
        response.json()["planned_amount"]
        == "4.0000"
    )

    response = client.delete(
        (
            f"/api/v1/treatments/"
            f"{treatment['id']}/components/"
            f"{plan['id']}"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 204
