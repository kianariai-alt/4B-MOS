from sqlalchemy.orm import Session

from backend.app.core.security import hash_password
from backend.app.models.user import User
from backend.app.repositories.user import UserRepository
from backend.app.schemas.user import (
    UserCreate,
    UserUpdate,
)


class UserNotFoundError(Exception):
    pass


class UsernameConflictError(Exception):
    pass


class UserService:
    @staticmethod
    def create_user(
        db: Session,
        payload: UserCreate,
    ) -> User:
        existing = UserRepository.get_by_username(
            db,
            payload.username,
        )

        if existing is not None:
            raise UsernameConflictError(
                f"Username '{payload.username}' already exists."
            )

        hashed_password = hash_password(
            payload.password
        )

        return UserRepository.create(
            db,
            username=payload.username,
            display_name=payload.display_name,
            password_hash=hashed_password,
            role=payload.role,
        )

    @staticmethod
    def get_user(
        db: Session,
        user_id: str,
    ) -> User:
        user = UserRepository.get_by_id(
            db,
            user_id,
        )

        if user is None:
            raise UserNotFoundError(
                f"User '{user_id}' was not found."
            )

        return user

    @staticmethod
    def list_users(
        db: Session,
        skip: int = 0,
        limit: int = 100,
    ) -> list[User]:
        return UserRepository.list(
            db,
            skip=skip,
            limit=limit,
        )

    @staticmethod
    def update_user(
        db: Session,
        user_id: str,
        payload: UserUpdate,
    ) -> User:
        user = UserService.get_user(
            db,
            user_id,
        )

        update_data = payload.model_dump(
            exclude_unset=True,
        )

        password = update_data.pop(
            "password",
            None,
        )

        if password is not None:
            update_data["password_hash"] = (
                hash_password(password)
            )

        return UserRepository.update(
            db,
            user,
            update_data,
        )