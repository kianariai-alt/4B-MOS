from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import settings


connect_args = {}

if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False


engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    connect_args=connect_args,
)


if settings.DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(
        dbapi_connection,
        connection_record,
    ):
        cursor = dbapi_connection.cursor()

        cursor.execute(
            "PRAGMA foreign_keys=ON"
        )

        cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()