def create_and_login_user(
    client,
    admin_headers,
    *,
    username: str,
    role: str,
) -> tuple[dict, dict]:
    password = "StrongPass123"

    create_response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": username,
            "display_name": username.title(),
            "password": password,
            "role": role,
        },
    )

    assert create_response.status_code == 201

    user = create_response.json()

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": password,
        },
    )

    assert login_response.status_code == 200

    token = login_response.json()[
        "access_token"
    ]

    headers = {
        "Authorization": f"Bearer {token}",
    }

    return user, headers


def test_user_list_requires_authentication(
    client,
):
    response = client.get(
        "/api/v1/users"
    )

    assert response.status_code == 401


def test_physician_cannot_list_users(
    client,
    admin_headers,
):
    _, headers = create_and_login_user(
        client,
        admin_headers,
        username="physician_rbac",
        role="physician",
    )

    response = client.get(
        "/api/v1/users",
        headers=headers,
    )

    assert response.status_code == 403


def test_viewer_cannot_create_user(
    client,
    admin_headers,
):
    _, headers = create_and_login_user(
        client,
        admin_headers,
        username="viewer_rbac",
        role="viewer",
    )

    response = client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "username": "forbiddenuser",
            "display_name": "Forbidden User",
            "password": "StrongPass123",
            "role": "viewer",
        },
    )

    assert response.status_code == 403


def test_admin_can_create_user(
    client,
    admin_headers,
):
    response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": "newdoctor",
            "display_name": "New Doctor",
            "password": "StrongPass123",
            "role": "physician",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["username"] == "newdoctor"
    assert data["role"] == "physician"


def test_physician_cannot_update_user(
    client,
    admin_headers,
):
    target_response = client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={
            "username": "targetuser",
            "display_name": "Target User",
            "password": "StrongPass123",
            "role": "viewer",
        },
    )

    assert target_response.status_code == 201

    target_id = target_response.json()["id"]

    _, physician_headers = create_and_login_user(
        client,
        admin_headers,
        username="physician_update",
        role="physician",
    )

    response = client.patch(
        f"/api/v1/users/{target_id}",
        headers=physician_headers,
        json={
            "role": "admin",
        },
    )

    assert response.status_code == 403