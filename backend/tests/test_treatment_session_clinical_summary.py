from backend.app.models.treatment_session_component import (
    TreatmentSessionComponent,
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
                f"CLIN-SUM-{suffix}"
            ),
            "first_name": "Clinical",
            "last_name": "Summary",
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
    amount: str,
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
        "actual_amount": amount,
    }

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


def get_summary(
    client,
    headers,
    session_id: str,
):
    return client.get(
        (
            "/api/v1/treatment-sessions/"
            f"{session_id}/clinical-summary"
        ),
        headers=headers,
    )


def test_summary_reports_aligned_plan(
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

    response = get_summary(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["has_plan"] is True
    assert (
        data["plan_alignment_status"]
        == "aligned"
    )
    assert data["has_deviations"] is False
    assert data["deviation_count"] == 0
    assert data["alert_count"] == 0
    assert (
        data["administered_record_count"]
        == 1
    )
    assert (
        data["variance"]["matched_count"]
        == 1
    )


def test_summary_reports_multiple_deviations(
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

    exosome = create_material(
        client,
        admin_headers,
        code="EXOSOME",
        name="Exosome",
        unit="vial",
    )

    ha = create_material(
        client,
        admin_headers,
        code="HA",
        name="Hyaluronic Acid",
    )

    acs_plan = create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=acs["id"],
        amount="3.0",
    )

    create_plan(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=exosome["id"],
        amount="1.0",
        unit="vial",
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
        amount="3.0",
        plan_id=acs_plan["id"],
    )

    administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=prgf["id"],
        amount="1.5",
        plan_id=prgf_plan["id"],
    )

    administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=ha["id"],
        amount="2.0",
    )

    response = get_summary(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["plan_alignment_status"]
        == "deviation_present"
    )

    assert data["has_deviations"] is True

    assert data["deviation_count"] == 3

    codes = {
        item["code"]
        for item in data["alerts"]
    }

    assert "UNDER_ADMINISTERED" in codes

    assert (
        "PLANNED_COMPONENT_OMITTED"
        in codes
    )

    assert (
        "UNPLANNED_ADMINISTRATION"
        in codes
    )


def test_summary_reports_no_plan(
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

    response = get_summary(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert data["has_plan"] is False

    assert (
        data["plan_alignment_status"]
        == "no_plan"
    )

    assert data["has_deviations"] is False

    codes = {
        item["code"]
        for item in data["alerts"]
    }

    assert "NO_TREATMENT_PLAN" in codes


def test_summary_reports_not_assessable(
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

    response = get_summary(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["plan_alignment_status"]
        == "not_assessable"
    )

    assert data["has_deviations"] is False

    assert (
        data["variance"][
            "unquantified_count"
        ]
        == 1
    )

    codes = {
        item["code"]
        for item in data["alerts"]
    }

    assert (
        "UNQUANTIFIED_COMPONENT"
        in codes
    )


def test_summary_detects_legacy_traceability_gap(
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

    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    legacy_record = (
        TreatmentSessionComponent(
            treatment_session_id=(
                session["id"]
            ),
            material_id=material["id"],
            actual_amount=1,
            unit="vial",
            sequence=1,
            lot_number=None,
            batch_number=None,
        )
    )

    db_session.add(
        legacy_record
    )

    db_session.commit()

    response = get_summary(
        client,
        admin_headers,
        session["id"],
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["traceability_issue_count"]
        == 1
    )

    codes = {
        item["code"]
        for item in data["alerts"]
    }

    assert "TRACEABILITY_MISSING" in codes


def test_viewer_can_read_clinical_summary(
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

    viewer_headers = (
        create_user_and_login(
            client,
            admin_headers,
            username="summaryviewer",
            role="viewer",
        )
    )

    response = get_summary(
        client,
        viewer_headers,
        session["id"],
    )

    assert response.status_code == 200


def test_missing_session_returns_404(
    client,
    admin_headers,
):
    response = get_summary(
        client,
        admin_headers,
        "missing-session-id",
    )

    assert response.status_code == 404
