from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database_revision import EXPECTED_DATABASE_REVISION
from backend.app.db.session import get_db


router = APIRouter(
    prefix="/health",
    tags=["System"],
)


@router.get("")
async def health_check():
    return {
        "status": "healthy",
        "application": settings.PROJECT_NAME,
        "version": settings.PROJECT_VERSION,
    }


@router.get("/ready")
def readiness(db: Session = Depends(get_db)):
    """Database readiness, distinct from liveness; never expose connection errors."""
    try:
        revisions = list(db.scalars(text("SELECT version_num FROM alembic_version")))
        if revisions != [EXPECTED_DATABASE_REVISION]:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        tables = set(inspect(db.connection()).get_table_names())
        required = {"users", "treatments", "treatment_sessions", "treatment_session_components", "session_finalizations"}
        if not required <= tables:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        if db.get_bind().dialect.name == "sqlite" and db.scalar(text("PRAGMA foreign_keys")) != 1:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready"}
