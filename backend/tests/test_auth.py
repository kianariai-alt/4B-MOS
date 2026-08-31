def create_user(
    client,
    *,
    username="doctor1",
    password="StrongPass123",
):
    response = client.post(
        "/api/v1/users",
        json={
            "username": username,
            "display_name": "Doctor One",
            "password": password,
            "role": "physician",
        },
    )

    assert response.status_code == 201

    return response.json()


def login(
    client,
    *,
    username="doctor1",
    password="StrongPass123",
):
    return client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": password,
        },
    )


def test_login_returns_access_token(client):
    create_user(client)

    response = login(client)

    assert response.status_code == 200

    data = response.json()

    assert data["token_type"] == "bearer"
    assert isinstance(
        data["access_token"],
        str,
    )
    assert len(data["access_token"]) > 20


def test_wrong_password_returns_401(client):
    create_user(client)

    response = login(
        client,
        password="WrongPassword123",
    )

    assert response.status_code == 401


def test_unknown_user_returns_401(client):
    response = login(
        client,
        username="missing",
    )

    assert response.status_code == 401


def test_auth_me_requires_token(client):
    response = client.get(
        "/api/v1/auth/me"
    )

    assert response.status_code == 401


def test_auth_me_returns_current_user(client):
    user = create_user(client)

    login_response = login(client)

    token = login_response.json()[
        "access_token"
    ]

    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {token}",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["id"] == user["id"]
    assert data["username"] == "doctor1"
    assert data["role"] == "physician"


def test_invalid_token_returns_401(client):
    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": "Bearer definitely-not-a-token",
        },
    )

    assert response.status_code == 401