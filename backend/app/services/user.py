from sqlalchemy.orm import Session
from sqlalchemy import func, select

from backend.app.core.security import hash_password
from backend.app.db.account_transactions import (
    AccountWriteConflictError, atomic_account_write, require_current_admin,
)
from backend.app.models.user import User
from backend.app.repositories.user import UserRepository
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.services.account_audit import account_snapshot
from backend.app.services.audit_context import actor_data
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

        attribution = actor_data(actor)
        user = UserRepository.create(
            db,
            username=payload.username,
            display_name=payload.display_name,
            password_hash=hashed_password,
            role=payload.role,
            commit=False,
        )
        AuditLogRepository.create(
            db, commit=False, entity_type="user", entity_id=user.id,
            event_type="user_created", **attribution,
            event_data={"schema_version": 1,
                        "source": "authenticated_admin" if actor is not None else "internal_service",
                        "after": account_snapshot(user)},
        )
        return user

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
        # Capture the acting admin BEFORE a self-rename/demotion changes it.
        attribution = actor_data(actor)
        before = account_snapshot(user)
        changed_fields = sorted(
            name for name, value in update_data.items()
            if name != "password" and before[name] != value
        )
        password_reset = "password" in update_data
        if not changed_fields and not password_reset:
            return user

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

        sessions_revoked = (
            password_reset
            or "role" in changed_fields
            or "is_active" in changed_fields
        )
        if sessions_revoked:
            update_data["auth_version"] = user.auth_version + 1

        user = UserRepository.update(
            db,
            user,
            update_data,
            commit=False,
        )
        after = account_snapshot(user)
        AuditLogRepository.create(
            db, commit=False, entity_type="user", entity_id=user.id,
            event_type="user_updated", **attribution,
            event_data={
                "schema_version": 1,
                "source": "authenticated_admin" if actor is not None else "internal_service",
                "changed_fields": sorted(changed_fields + (["password"] if password_reset else [])),
                "before": {name: before[name] for name in changed_fields},
                "after": {name: after[name] for name in changed_fields},
                "password_reset": password_reset,
                "sessions_revoked": sessions_revoked,
            },
        )
        return user
