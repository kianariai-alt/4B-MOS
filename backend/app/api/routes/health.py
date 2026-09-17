from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.readiness import database_readiness_issues
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
        if database_readiness_issues(db):
            return JSONResponse(status_code=503, content={"status": "not_ready"})
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready"}
