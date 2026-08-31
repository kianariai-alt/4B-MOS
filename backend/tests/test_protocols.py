def protocol_payload(
    code="PRP-KNEE",
    version="1.0",
    treatment_type="PRP",
):
    return {
        "code": code,
        "name": "Knee Orthobiologic Protocol",
        "treatment_type": treatment_type,
        "version": version,
        "description": "Structured protocol",
        "preparation_parameters": {
            "centrifuge": "example",
        },
        "administration_parameters": {
            "route": "intra-articular",
        },
        "monitoring_parameters": {
            "follow_up": "configured",
        },
    }


def test_create_protocol(client):
    response = client.post(
        "/api/v1/protocols",
        json=protocol_payload(),
    )

    assert response.status_code == 201

    data = response.json()

    assert data["code"] == "PRP-KNEE"
    assert data["version"] == "1.0"
    assert data["treatment_type"] == "PRP"
    assert data["is_active"] is True


def test_same_code_and_version_returns_409(client):
    payload = protocol_payload()

    first = client.post(
        "/api/v1/protocols",
        json=payload,
    )

    second = client.post(
        "/api/v1/protocols",
        json=payload,
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_same_code_different_version_allowed(client):
    first = client.post(
        "/api/v1/protocols",
        json=protocol_payload(
            version="1.0",
        ),
    )

    second = client.post(
        "/api/v1/protocols",
        json=protocol_payload(
            version="2.0",
        ),
    )

    assert first.status_code == 201
    assert second.status_code == 201


def test_list_protocols(client):
    client.post(
        "/api/v1/protocols",
        json=protocol_payload(),
    )

    response = client.get(
        "/api/v1/protocols"
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_filter_protocols_by_treatment_type(client):
    client.post(
        "/api/v1/protocols",
        json=protocol_payload(
            code="PRP-001",
            treatment_type="PRP",
        ),
    )

    client.post(
        "/api/v1/protocols",
        json=protocol_payload(
            code="ACS-001",
            treatment_type="ACS",
        ),
    )

    response = client.get(
        "/api/v1/protocols?treatment_type=ACS"
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["treatment_type"] == "ACS"


def test_deactivate_protocol(client):
    create_response = client.post(
        "/api/v1/protocols",
        json=protocol_payload(),
    )

    protocol_id = create_response.json()["id"]

    response = client.delete(
        f"/api/v1/protocols/{protocol_id}"
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False