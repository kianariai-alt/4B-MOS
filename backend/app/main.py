from fastapi import FastAPI

from backend.app.api.router import api_router
from backend.app.core.config import settings


def create_application() -> FastAPI:
    application = FastAPI(
        title=settings.PROJECT_NAME,
        description="4B Medical Operating System",
        version=settings.PROJECT_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    application.include_router(
        api_router,
        prefix=settings.API_V1_PREFIX,
    )

    return application


app = create_application()


@app.get("/", tags=["System"])
async def root():
    return {
        "application": settings.PROJECT_NAME,
        "version": settings.PROJECT_VERSION,
        "status": "running",
        "api": settings.API_V1_PREFIX,
        "docs": "/docs",
    }