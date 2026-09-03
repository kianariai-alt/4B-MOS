def create_treatment(client, admin_headers, *, suffix: str) -> dict:
    response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": f"EXEC-INTEGRITY-{suffix}",
            "first_name": "Execution",
            "last_name": "Integrity",
        },
    )
    assert response.status_code == 201
    patient = response.json()

    response = client.post(
        f"/api/v1/patients/{patient['id']}/visits",
        headers=admin_headers,
        json={"body_region": "Knee"},
    )
    assert response.status_code == 201
    visit = response.json()

    response = client.post(
        f"/api/v1/visits/{visit['id']}/treatments",
        headers=admin_headers,
        json={
            "treatment_type": "ACS",
            "body_region": "Knee",
        },
    )
    assert response.status_code == 201
    return response.json()


def create_material(client, admin_headers, *, code: str, name: str) -> dict:
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
    amount: str,
) -> dict:
    response = client.post(
        f"/api/v1/treatments/{treatment_id}/components",
        headers=admin_headers,
        json={
            "material_id": material_id,
            "planned_amount": amount,
        },
    )
    assert response.status_code == 201
    return response.json()


def create_session(client, admin_headers, *, treatment_id: str) -> dict:
    response = client.post(
        f"/api/v1/treatments/{treatment_id}/sessions",
        headers=admin_headers,
        json={
            "session_number": 1,
            "body_region": "Knee",
        },
    )
    assert response.status_code == 201
    return response.json()


def transition(client, headers, *, session_id: str, target: str):
    return client.patch(
        f"/api/v1/treatment-sessions/{session_id}/workflow",
        headers=headers,
        json={"operational_status": target},
    )


def move_to_in_treatment(client, headers, *, session_id: str) -> None:
    for target in ("checked_in", "ready", "in_treatment"):
        response = transition(
            client,
            headers,
            session_id=session_id,
            target=target,
        )
        assert response.status_code == 200


def administer(
    client,
    headers,
    *,
    session_id: str,
    material_id: str,
    plan_id: str,
    amount: str,
) -> dict:
    response = client.post(
        f"/api/v1/treatment-sessions/{session_id}/components",
        headers=headers,
        json={
            "material_id": material_id,
            "treatment_component_id": plan_id,
            "actual_amount": amount,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_execution_integrity_aligned_plan_survives_full_lifecycle(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix="ALIGNED",
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

    plan = add_plan_component(
        client,
        admin_headers,
        treatment_id=treatment["id"],
        material_id=acs["id"],
        amount="3.0",
    )
    session = create_session(
        client,
        admin_headers,
        treatment_id=treatment["id"],
    )

    move_to_in_treatment(
        client,
        admin_headers,
        session_id=session["id"],
    )

    # Once execution starts, the treatment plan must be frozen.
    response = client.post(
        f"/api/v1/treatments/{treatment['id']}/components",
        headers=admin_headers,
        json={
            "material_id": prgf["id"],
            "planned_amount": "2.0",
        },
    )
    assert response.status_code == 409

    administration = administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=acs["id"],
        plan_id=plan["id"],
        amount="3.0",
    )
    assert administration["treatment_component_id"] == plan["id"]

    response = client.get(
        f"/api/v1/treatment-sessions/{session['id']}/variance",
        headers=admin_headers,
    )
    assert response.status_code == 200
    variance = response.json()
    assert variance["planned_count"] == 1
    assert variance["matched_count"] == 1
    assert variance["omitted_count"] == 0
    assert variance["unplanned_count"] == 0

    response = client.get(
        f"/api/v1/treatment-sessions/{session['id']}/clinical-summary",
        headers=admin_headers,
    )
    assert response.status_code == 200
    summary = response.json()
    assert summary["has_plan"] is True
    assert summary["plan_alignment_status"] == "aligned"
    assert summary["has_deviations"] is False
    assert summary["administered_record_count"] == 1

    response = client.get(
        f"/api/v1/treatment-sessions/{session['id']}/completion-check",
        headers=admin_headers,
    )
    assert response.status_code == 200
    completion = response.json()
    assert completion["can_complete"] is True
    assert completion["readiness"] == "ready"

    response = transition(
        client,
        admin_headers,
        session_id=session["id"],
        target="completed",
    )
    assert response.status_code == 200
    completed = response.json()
    assert completed["status"] == "completed"
    assert completed["operational_status"] == "completed"

    # Clinical interpretation must remain stable after completion.
    response = client.get(
        f"/api/v1/treatment-sessions/{session['id']}/variance",
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["matched_count"] == 1

    response = client.get(
        f"/api/v1/treatment-sessions/{session['id']}/clinical-summary",
        headers=admin_headers,
    )
    assert response.status_code == 200
    assert response.json()["plan_alignment_status"] == "aligned"


def test_execution_integrity_variance_warning_allows_completion(
    client,
    admin_headers,
):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix="WARNING",
    )
    material = create_material(
        client,
        admin_headers,
        code="PL",
        name="Platelet Lysate",
    )
    plan = add_plan_component(
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

    move_to_in_treatment(
        client,
        admin_headers,
        session_id=session["id"],
    )
    administer(
        client,
        admin_headers,
        session_id=session["id"],
        material_id=material["id"],
        plan_id=plan["id"],
        amount="2.5",
    )

    response = client.get(
        f"/api/v1/treatment-sessions/{session['id']}/variance",
        headers=admin_headers,
    )
    assert response.status_code == 200
    variance = response.json()
    assert variance["under_administered_count"] == 1

    response = client.get(
        f"/api/v1/treatment-sessions/{session['id']}/clinical-summary",
        headers=admin_headers,
    )
    assert response.status_code == 200
    summary = response.json()
    assert summary["plan_alignment_status"] == "deviation_present"
    assert summary["has_deviations"] is True

    response = client.get(
        f"/api/v1/treatment-sessions/{session['id']}/completion-check",
        headers=admin_headers,
    )
    assert response.status_code == 200
    completion = response.json()
    assert completion["can_complete"] is True
    assert completion["readiness"] == "ready_with_warnings"

    warning_codes = {
        issue["code"]
        for issue in completion["issues"]
        if issue["severity"] == "warning"
    }
    assert "UNDER_ADMINISTERED" in warning_codes

    response = transition(
        client,
        admin_headers,
        session_id=session["id"],
        target="completed",
    )
    assert response.status_code == 200
