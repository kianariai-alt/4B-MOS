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
                f"VAR-{suffix}"
            ),
            "first_name": "Variance",
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
) -> dict:
    response = client.post(
        "/api/v1/orthobiologic-materials",
        headers=admin_headers,
        json={
            "code": code,
            "name": name,
            "default_unit": unit,
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
    amount: str | None,
    unit: str | None = None,
) -> dict:
    payload = {
        "material_id": material_id,
    }

    if amount is not None:
        payload["planned_amount"] = amount

    if unit is not None:
        payload["unit"] = unit

    response = client.post(
        (
            f"/api/v1/treatments/"
            f"{treatment_id}/components"
        ),
        headers=admin_headers,
        json=payload,
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


def administer(
    client,
    admin_headers,
    *,
    session_id: str,
    material_id: str,
    amount: str | None,
    plan_id: str | None = None,
    unit: str | None = None,
) -> dict:
    ensure_in_treatment(
        client,
        admin_headers,
        session_id,
    )

    payload = {
        "material_id": material_id,
    }

    if amount is not None:
        payload["actual_amount"] = amount

    if plan_id is not None:
        payload[
            "treatment_component_id"
        ] = plan_id

    if unit is not None:
        payload["unit"] = unit

    response = client.post(
        (
            "/api/v1/treatment-sessions/"
            f"{session_id}/components"
        ),
        headers=admin_headers,
        json=payload,
    )

    assert response.status_code == 201

    return response.json()


def get_variance(
    client,
    headers,
    session_id: str,
):
    return client.get(
        (
            "/api/v1/treatment-sessions/"
            f"{session_id}/variance"
        ),
        headers=headers,
    )


def test_variance_reports_matched_component(
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
        amount="3.0",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        amount="3.0",
        plan_id=plan["id"],
    )

    response = get_variance(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["planned_count"] == 1
    assert data["matched_count"] == 1
    assert data["omitted_count"] == 0
    assert data["unplanned_count"] == 0

    item = data["components"][0]

    assert item["status"] == "matched"
    assert item["difference"] == "0.0000"
    assert item["actual_amount"] == "3.0000"


def test_variance_reports_under_and_over(
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

    acs_plan = create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=acs["id"],
        amount="3.0",
    )

    prgf_plan = create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=prgf["id"],
        amount="2.0",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=acs["id"],
        amount="2.5",
        plan_id=acs_plan["id"],
    )

    administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=prgf["id"],
        amount="2.5",
        plan_id=prgf_plan["id"],
    )

    response = get_variance(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["under_administered_count"]
        == 1
    )

    assert (
        data["over_administered_count"]
        == 1
    )

    by_code = {
        item["material_code"]: item
        for item in data["components"]
    }

    assert (
        by_code["ACS"]["status"]
        == "under_administered"
    )

    assert (
        by_code["ACS"]["difference"]
        == "-0.5000"
    )

    assert (
        by_code["PRGF"]["status"]
        == "over_administered"
    )

    assert (
        by_code["PRGF"]["difference"]
        == "0.5000"
    )


def test_variance_reports_omitted_component(
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
        code="PL",
        name="Platelet Lysate",
    )

    create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=material["id"],
        amount="3.0",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    response = get_variance(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["omitted_count"] == 1
    assert (
        data["components"][0]["status"]
        == "omitted"
    )

    assert (
        data["components"][0]["actual_amount"]
        is None
    )


def test_variance_reports_unplanned_administration(
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

    create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=planned_material["id"],
        amount="3.0",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=extra_material["id"],
        amount="2.0",
    )

    response = get_variance(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["planned_count"] == 1
    assert data["omitted_count"] == 1
    assert data["unplanned_count"] == 1
    assert (
        len(
            data[
                "unplanned_administrations"
            ]
        )
        == 1
    )

    unplanned = (
        data[
            "unplanned_administrations"
        ][0]
    )

    assert (
        unplanned["material_code"]
        == "HA"
    )

    assert (
        unplanned["actual_amount"]
        == "2.0000"
    )


def test_multiple_administrations_are_summed(
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
    )

    plan = create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=material["id"],
        amount="2.0",
        unit="vial",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        amount="1.0",
        plan_id=plan["id"],
        unit="vial",
    )

    administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        amount="1.0",
        plan_id=plan["id"],
        unit="vial",
    )

    response = get_variance(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()
    item = data["components"][0]

    assert item["status"] == "matched"
    assert item["actual_amount"] == "2.0000"
    assert item["administration_count"] == 2

    assert (
        data["linked_administration_count"]
        == 2
    )


def test_variance_reports_unit_mismatch(
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
        unit="ml",
    )

    plan = create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=material["id"],
        amount="2.0",
        unit="ml",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        amount="2.0",
        plan_id=plan["id"],
        unit="vial",
    )

    response = get_variance(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["unit_mismatch_count"]
        == 1
    )

    assert (
        data["components"][0]["status"]
        == "unit_mismatch"
    )

    assert (
        data["components"][0]["difference"]
        is None
    )


def test_variance_reports_unquantified(
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
        code="SVF",
        name="Stromal Vascular Fraction",
    )

    plan = create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=material["id"],
        amount=None,
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        amount="3.0",
        plan_id=plan["id"],
    )

    response = get_variance(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["unquantified_count"]
        == 1
    )

    assert (
        data["components"][0]["status"]
        == "unquantified"
    )


def test_viewer_can_read_variance(
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
        amount="3.0",
    )

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    viewer_headers = create_user_and_login(
        client,
        admin_headers,
        username="varianceviewer",
        role="viewer",
    )

    response = get_variance(
        client,
        viewer_headers,
        session["id"],
    )

    assert response.status_code == 200


def test_missing_session_returns_404(
    client,
    admin_headers,
):
    response = get_variance(
        client,
        admin_headers,
        "missing-session-id",
    )

    assert response.status_code == 404
