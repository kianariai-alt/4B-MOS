from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import settings


connect_args = {}

if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
elif settings.DATABASE_URL.startswith("postgresql"):
    # Bound waits for PostgreSQL row/table locks so the service-layer
    # contention handlers can return a controlled conflict instead of leaving
    # a request blocked indefinitely. ``options`` is a libpq startup option
    # supported by the pinned Psycopg driver.
    connect_args["options"] = (
        f"-c lock_timeout={settings.DATABASE_LOCK_TIMEOUT_MS}ms"
    )


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
