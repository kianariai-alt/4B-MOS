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
    create_response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": username,
            "display_name": username,
            "password": "StrongPass123",
            "role": role,
        },
    )

    assert create_response.status_code == 201

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": "StrongPass123",
        },
    )

    assert login_response.status_code == 200

    token = login_response.json()[
        "access_token"
    ]

    return {
        "Authorization": f"Bearer {token}",
    }


def create_material(
    client,
    admin_headers,
    *,
    code: str = "ACS",
    name: str = "Autologous Conditioned Serum",
    category: str = "orthobiologic",
    default_unit: str | None = "ml",
    is_autologous: bool = True,
    requires_lot_tracking: bool = False,
) -> dict:
    response = client.post(
        "/api/v1/orthobiologic-materials",
        headers=admin_headers,
        json={
            "code": code,
            "name": name,
            "category": category,
            "default_unit": default_unit,
            "is_autologous": is_autologous,
            "requires_lot_tracking": (
                requires_lot_tracking
            ),
        },
    )

    assert response.status_code == 201

    return response.json()


def test_admin_can_create_normalized_material(
    client,
    admin_headers,
):
    response = client.post(
        "/api/v1/orthobiologic-materials",
        headers=admin_headers,
        json={
            "code": "  acs  ",
            "name": (
                "  Autologous Conditioned Serum  "
            ),
            "category": "  Orthobiologic  ",
            "default_unit": " ML ",
            "is_autologous": True,
            "requires_lot_tracking": False,
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["code"] == "ACS"
    assert (
        data["name"]
        == "Autologous Conditioned Serum"
    )
    assert data["category"] == "orthobiologic"
    assert data["default_unit"] == "ml"
    assert data["is_autologous"] is True
    assert data["is_active"] is True


def test_blank_material_code_is_rejected(
    client,
    admin_headers,
):
    response = client.post(
        "/api/v1/orthobiologic-materials",
        headers=admin_headers,
        json={
            "code": "   ",
            "name": "Invalid Material",
        },
    )

    assert response.status_code == 422


def test_duplicate_material_code_is_rejected(
    client,
    admin_headers,
):
    create_material(
        client,
        admin_headers,
        code="ACS",
    )

    response = client.post(
        "/api/v1/orthobiologic-materials",
        headers=admin_headers,
        json={
            "code": "  acs  ",
            "name": "Duplicate ACS",
        },
    )

    assert response.status_code == 409


def test_physician_cannot_create_master_material(
    client,
    admin_headers,
):
    physician_headers = create_user_and_login(
        client,
        admin_headers,
        username="materialphysician",
        role="physician",
    )

    response = client.post(
        "/api/v1/orthobiologic-materials",
        headers=physician_headers,
        json={
            "code": "PRGF",
            "name": "Plasma Rich in Growth Factors",
        },
    )

    assert response.status_code == 403


def test_viewer_can_read_material_catalog(
    client,
    admin_headers,
):
    material = create_material(
        client,
        admin_headers,
    )

    viewer_headers = create_user_and_login(
        client,
        admin_headers,
        username="materialviewer",
        role="viewer",
    )

    list_response = client.get(
        "/api/v1/orthobiologic-materials",
        headers=viewer_headers,
    )

    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    get_response = client.get(
        (
            "/api/v1/"
            "orthobiologic-materials/"
            f"{material['id']}"
        ),
        headers=viewer_headers,
    )

    assert get_response.status_code == 200
    assert (
        get_response.json()["id"]
        == material["id"]
    )


def test_deactivated_material_is_hidden_by_default(
    client,
    admin_headers,
):
    material = create_material(
        client,
        admin_headers,
    )

    delete_response = client.delete(
        (
            "/api/v1/"
            "orthobiologic-materials/"
            f"{material['id']}"
        ),
        headers=admin_headers,
    )

    assert delete_response.status_code == 200
    assert (
        delete_response.json()["is_active"]
        is False
    )

    default_response = client.get(
        "/api/v1/orthobiologic-materials",
        headers=admin_headers,
    )

    assert default_response.status_code == 200
    assert default_response.json() == []

    all_response = client.get(
        (
            "/api/v1/"
            "orthobiologic-materials"
            "?active_only=false"
        ),
        headers=admin_headers,
    )

    assert all_response.status_code == 200
    assert len(all_response.json()) == 1
    assert (
        all_response.json()[0]["is_active"]
        is False
    )


def test_material_catalog_can_filter_by_category(
    client,
    admin_headers,
):
    create_material(
        client,
        admin_headers,
        code="ACS",
        name="Autologous Conditioned Serum",
        category="orthobiologic",
    )

    create_material(
        client,
        admin_headers,
        code="EXOSOME",
        name="Exosome",
        category="biologic",
        default_unit="vial",
        is_autologous=False,
        requires_lot_tracking=True,
    )

    response = client.get(
        (
            "/api/v1/"
            "orthobiologic-materials"
            "?category=biologic"
        ),
        headers=admin_headers,
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["code"] == "EXOSOME"
    assert data[0]["category"] == "biologic"


def test_material_lifecycle_is_audited_once(
    client,
    admin_headers,
    db_session,
):
    material = create_material(
        client,
        admin_headers,
        code="PRGF",
        name="Plasma Rich in Growth Factors",
    )

    first_delete = client.delete(
        (
            "/api/v1/"
            "orthobiologic-materials/"
            f"{material['id']}"
        ),
        headers=admin_headers,
    )

    assert first_delete.status_code == 200

    second_delete = client.delete(
        (
            "/api/v1/"
            "orthobiologic-materials/"
            f"{material['id']}"
        ),
        headers=admin_headers,
    )

    assert second_delete.status_code == 200

    db_session.expire_all()

    statement = (
        select(AuditLog)
        .where(
            AuditLog.entity_type
            == "orthobiologic_material",
            AuditLog.entity_id
            == material["id"],
        )
        .order_by(
            AuditLog.created_at.asc(),
            AuditLog.id.asc(),
        )
    )

    logs = list(
        db_session.scalars(statement).all()
    )

    assert len(logs) == 2

    assert (
        logs[0].event_type
        == "orthobiologic_material_created"
    )

    assert (
        logs[1].event_type
        == "orthobiologic_material_deactivated"
    )

    assert logs[0].actor_role == "admin"
    assert logs[1].actor_role == "admin"

    assert logs[0].to_state == "active"
    assert logs[1].from_state == "active"
    assert logs[1].to_state == "inactive"


def test_unknown_material_returns_404(
    client,
    admin_headers,
):
    missing_id = (
        "00000000-0000-0000-"
        "0000-000000000000"
    )

    get_response = client.get(
        (
            "/api/v1/"
            "orthobiologic-materials/"
            f"{missing_id}"
        ),
        headers=admin_headers,
    )

    assert get_response.status_code == 404

    delete_response = client.delete(
        (
            "/api/v1/"
            "orthobiologic-materials/"
            f"{missing_id}"
        ),
        headers=admin_headers,
    )

    assert delete_response.status_code == 404
