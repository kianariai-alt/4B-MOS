from fastapi import APIRouter

from backend.app.core.config import settings


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