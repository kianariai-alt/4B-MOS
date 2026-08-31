from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.user import User


class UserRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        user_id: str,
    ) -> User | None:
        return db.get(
            User,
            user_id,
        )

    @staticmethod
    def get_by_username(
        db: Session,
        username: str,
    ) -> User | None:
        statement = select(
            User
        ).where(
            User.username == username
        )

        return db.scalar(statement)

    @staticmethod
    def list(
        db: Session,
        skip: int = 0,
        limit: int = 100,
    ) -> list[User]:
        statement = (
            select(User)
            .order_by(
                User.username.asc()
            )
            .offset(skip)
            .limit(limit)
        )

        return list(
            db.scalars(statement).all()
        )

    @staticmethod
    def create(
        db: Session,
        *,
        username: str,
        display_name: str,
        password_hash: str,
        role: str,
    ) -> User:
        user = User(
            username=username,
            display_name=display_name,
            password_hash=password_hash,
            role=role,
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        return user

    @staticmethod
    def update(
        db: Session,
        user: User,
        update_data: dict,
    ) -> User:
        for field_name, value in update_data.items():
            setattr(
                user,
                field_name,
                value,
            )

        db.add(user)
        db.commit()
        db.refresh(user)

        return user