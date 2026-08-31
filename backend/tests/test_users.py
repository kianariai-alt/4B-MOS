import pytest
from sqlalchemy import select

from backend.app.core.security import (
    verify_password,
)
from backend.app.models.user import User


@pytest.fixture(autouse=True)
def authenticate_user_tests(
    client,
    admin_headers,
):
    client.headers.update(
        admin_headers
    )


def user_payload(
    username="doctor1",
    password="StrongPass123",
    role="physician",
):
    return {
        "username": username,
        "display_name": "Doctor One",
        "password": password,
        "role": role,
    }


def test_create_user(client):
    response = client.post(
        "/api/v1/users",
        json=user_payload(),
    )

    assert response.status_code == 201

    data = response.json()

    assert data["username"] == "doctor1"

    assert (
        data["display_name"]
        == "Doctor One"
    )

    assert data["role"] == "physician"
    assert data["is_active"] is True

    assert "password" not in data
    assert "password_hash" not in data


def test_username_is_normalized(
    client,
):
    response = client.post(
        "/api/v1/users",
        json=user_payload(
            username="  DoctorABC  ",
        ),
    )

    assert response.status_code == 201

    assert (
        response.json()["username"]
        == "doctorabc"
    )


def test_duplicate_username_returns_409(
    client,
):
    first = client.post(
        "/api/v1/users",
        json=user_payload(),
    )

    second = client.post(
        "/api/v1/users",
        json=user_payload(),
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_password_is_hashed_in_database(
    client,
    db_session,
):
    password = "StrongPass123"

    response = client.post(
        "/api/v1/users",
        json=user_payload(
            password=password,
        ),
    )

    assert response.status_code == 201

    user_id = response.json()["id"]

    user = db_session.scalar(
        select(User).where(
            User.id == user_id
        )
    )

    assert user is not None

    assert (
        user.password_hash
        != password
    )

    assert verify_password(
        password,
        user.password_hash,
    )


def test_list_users(client):
    first = client.post(
        "/api/v1/users",
        json=user_payload(
            username="doctor1",
        ),
    )

    assert first.status_code == 201

    second = client.post(
        "/api/v1/users",
        json=user_payload(
            username="nurse1",
            role="nurse",
        ),
    )

    assert second.status_code == 201

    response = client.get(
        "/api/v1/users"
    )

    assert response.status_code == 200

    users = response.json()

    assert len(users) == 3

    usernames = {
        item["username"]
        for item in users
    }

    assert "testadmin" in usernames
    assert "doctor1" in usernames
    assert "nurse1" in usernames


def test_update_user(client):
    create_response = client.post(
        "/api/v1/users",
        json=user_payload(),
    )

    assert create_response.status_code == 201

    user_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/users/{user_id}",
        json={
            "display_name": "Updated Doctor",
            "role": "admin",
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["display_name"]
        == "Updated Doctor"
    )

    assert data["role"] == "admin"


def test_update_password_rehashes_password(
    client,
    db_session,
):
    create_response = client.post(
        "/api/v1/users",
        json=user_payload(
            password="OldPassword123",
        ),
    )

    assert create_response.status_code == 201

    user_id = create_response.json()["id"]

    response = client.patch(
        f"/api/v1/users/{user_id}",
        json={
            "password": "NewPassword456",
        },
    )

    assert response.status_code == 200

    db_session.expire_all()

    user = db_session.get(
        User,
        user_id,
    )

    assert user is not None

    assert verify_password(
        "NewPassword456",
        user.password_hash,
    )

    assert not verify_password(
        "OldPassword123",
        user.password_hash,
    )


def test_invalid_role_returns_422(
    client,
):
    response = client.post(
        "/api/v1/users",
        json=user_payload(
            role="supreme_overlord",
        ),
    )

    assert response.status_code == 422


def test_short_password_returns_422(
    client,
):
    response = client.post(
        "/api/v1/users",
        json=user_payload(
            password="123",
        ),
    )

    assert response.status_code == 422


def test_missing_user_returns_404(
    client,
):
    response = client.get(
        "/api/v1/users/not-real"
    )

    assert response.status_code == 404