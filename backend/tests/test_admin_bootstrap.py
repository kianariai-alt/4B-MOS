from backend.app.core.security import (
    hash_password,
    verify_password,
)
from backend.app.models.user import User


def bootstrap_payload():
    return {
        "username": "systemadmin",
        "display_name": (
            "System Administrator"
        ),
        "password": "StrongAdmin123",
    }


def test_first_admin_can_be_bootstrapped(
    client,
    db_session,
):
    response = client.post(
        "/api/v1/auth/bootstrap-admin",
        json=bootstrap_payload(),
    )

    assert response.status_code == 201

    data = response.json()

    assert (
        data["username"]
        == "systemadmin"
    )

    assert (
        data["display_name"]
        == "System Administrator"
    )

    assert data["role"] == "admin"

    assert data["is_active"] is True

    assert "password" not in data

    assert "password_hash" not in data

    user = db_session.get(
        User,
        data["id"],
    )

    assert user is not None

    assert verify_password(
        "StrongAdmin123",
        user.password_hash,
    )


def test_bootstrap_cannot_run_twice(
    client,
):
    first = client.post(
        "/api/v1/auth/bootstrap-admin",
        json=bootstrap_payload(),
    )

    assert first.status_code == 201

    second = client.post(
        "/api/v1/auth/bootstrap-admin",
        json={
            "username": "anotheradmin",
            "display_name": "Another Admin",
            "password": "AnotherStrong123",
        },
    )

    assert second.status_code == 409


def test_existing_user_disables_bootstrap(
    client,
    db_session,
):
    user = User(
        username="existinguser",
        display_name="Existing User",
        password_hash=hash_password(
            "StrongPass123"
        ),
        role="viewer",
        is_active=True,
    )

    db_session.add(user)
    db_session.commit()

    response = client.post(
        "/api/v1/auth/bootstrap-admin",
        json=bootstrap_payload(),
    )

    assert response.status_code == 409


def test_bootstrapped_admin_can_login(
    client,
):
    bootstrap_response = client.post(
        "/api/v1/auth/bootstrap-admin",
        json=bootstrap_payload(),
    )

    assert (
        bootstrap_response.status_code
        == 201
    )

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "systemadmin",
            "password": "StrongAdmin123",
        },
    )

    assert login_response.status_code == 200

    data = login_response.json()

    assert (
        data["token_type"]
        == "bearer"
    )

    assert len(
        data["access_token"]
    ) > 20


def test_bootstrapped_admin_token_resolves_me(
    client,
):
    bootstrap_response = client.post(
        "/api/v1/auth/bootstrap-admin",
        json=bootstrap_payload(),
    )

    assert (
        bootstrap_response.status_code
        == 201
    )

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "systemadmin",
            "password": "StrongAdmin123",
        },
    )

    assert login_response.status_code == 200

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

    assert (
        data["username"]
        == "systemadmin"
    )

    assert data["role"] == "admin"