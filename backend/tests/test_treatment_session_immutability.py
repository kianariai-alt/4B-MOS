def create_treatment(client, admin_headers, *, suffix: str) -> dict:
    response = client.post(
        "/api/v1/patients",
        headers=admin_headers,
        json={
            "patient_code": f"IMMUTABLE-{suffix}",
            "first_name": "Immutable",
            "last_name": "Session",
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


def create_material(client, admin_headers, *, code: str) -> dict:
    response = client.post(
        "/api/v1/orthobiologic-materials",
        headers=admin_headers,
        json={
            "code": code,
            "name": code,
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
        f"/api/v1/treatments/{treatment_id}/components",
        headers=admin_headers,
        json={
            "material_id": material_id,
            "planned_amount": "3.0",
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
            "notes": "before",
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


def test_completed_session_is_immutable(client, admin_headers):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix="COMPLETED",
    )
    material = create_material(
        client,
        admin_headers,
        code="IMM-ACS",
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

    move_to_in_treatment(
        client,
        admin_headers,
        session_id=session["id"],
    )

    response = client.post(
        f"/api/v1/treatment-sessions/{session['id']}/components",
        headers=admin_headers,
        json={
            "material_id": material["id"],
            "treatment_component_id": plan["id"],
            "actual_amount": "3.0",
        },
    )
    assert response.status_code == 201

    response = transition(
        client,
        admin_headers,
        session_id=session["id"],
        target="completed",
    )
    assert response.status_code == 200

    response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        headers=admin_headers,
        json={
            "notes": "changed after completion",
            "outcome_summary": "rewritten outcome",
            "adverse_events": "rewritten adverse event",
        },
    )
    assert response.status_code == 409
    assert "immutable" in response.json()["detail"].lower()

    response = client.get(
        f"/api/v1/treatment-sessions/{session['id']}",
        headers=admin_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["notes"] == "before"
    assert data["outcome_summary"] is None
    assert data["adverse_events"] is None


def test_cancelled_session_is_immutable(client, admin_headers):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix="CANCELLED",
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

    response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        headers=admin_headers,
        json={"notes": "changed after cancellation"},
    )
    assert response.status_code == 409
    assert "immutable" in response.json()["detail"].lower()


def test_in_treatment_session_remains_mutable(client, admin_headers):
    treatment = create_treatment(
        client,
        admin_headers,
        suffix="ACTIVE",
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

    response = client.patch(
        f"/api/v1/treatment-sessions/{session['id']}",
        headers=admin_headers,
        json={
            "notes": "documented during treatment",
            "outcome_summary": "clinical response",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["notes"] == "documented during treatment"
    assert data["outcome_summary"] == "clinical response"
