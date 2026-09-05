from sqlalchemy.orm import Session
from sqlalchemy import func, select

from backend.app.core.security import hash_password
from backend.app.db.account_transactions import (
    AccountWriteConflictError, atomic_account_write, require_current_admin,
)
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


class LastActiveAdminError(AccountWriteConflictError):
    pass


class UserService:
    @staticmethod
    @atomic_account_write
    def create_user(
        db: Session,
        payload: UserCreate,
        actor: User | None = None,
    ) -> User:
        require_current_admin(db, actor)
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
            commit=False,
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
    @atomic_account_write
    def update_user(
        db: Session,
        user_id: str,
        payload: UserUpdate,
        actor: User | None = None,
    ) -> User:
        require_current_admin(db, actor)
        user = UserService.get_user(
            db,
            user_id,
        )

        update_data = payload.model_dump(
            exclude_unset=True,
        )

        removes_admin = (
            user.role == "admin" and user.is_active
            and (update_data.get("role", user.role) != "admin"
                 or not update_data.get("is_active", user.is_active))
        )
        if removes_admin:
            active_admins = db.scalar(select(func.count()).select_from(User).where(
                User.role == "admin", User.is_active.is_(True),
            ))
            if active_admins <= 1:
                raise LastActiveAdminError(
                    "The last active administrator cannot be disabled or demoted. "
                    "Create or activate another administrator first."
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
            commit=False,
        )
