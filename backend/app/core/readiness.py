"""Shared, read-only database readiness checks.

The public readiness endpoint and the release preflight command use this module
so they cannot silently drift to different definitions of a ready schema.
Only stable issue codes leave this module; database errors and connection
details remain private to the process.
"""

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from backend.app.core.database_revision import EXPECTED_DATABASE_REVISION


REQUIRED_DATABASE_TABLES = frozenset(
    {
        "users",
        "treatments",
        "treatment_sessions",
        "treatment_session_components",
        "session_finalizations",
        "session_amendments",
        "session_amendment_reviews",
    }
)


def database_readiness_issues(db: Session) -> tuple[str, ...]:
    """Return stable readiness issue codes without mutating the database.

    SQLAlchemy exceptions intentionally propagate to the caller. The HTTP
    endpoint and release preflight command each convert them to a redacted
    not-ready result and roll back the failed read transaction.
    """

    issues: list[str] = []
    revisions = list(db.scalars(text("SELECT version_num FROM alembic_version")))

    if revisions != [EXPECTED_DATABASE_REVISION]:
        issues.append("database_revision_mismatch")

    tables = set(inspect(db.connection()).get_table_names())
    if not REQUIRED_DATABASE_TABLES <= tables:
        issues.append("required_tables_missing")

    if (
        db.get_bind().dialect.name == "sqlite"
        and db.scalar(text("PRAGMA foreign_keys")) != 1
    ):
        issues.append("sqlite_foreign_keys_disabled")

    return tuple(issues)
