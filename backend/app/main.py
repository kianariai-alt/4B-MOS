from fastapi import FastAPI
from fastapi.responses import JSONResponse

from backend.app.api.router import api_router
from backend.app.core.config import settings
from backend.app.db.transactions import ClinicalWriteConflictError


def create_application() -> FastAPI:
    application = FastAPI(
        title=settings.PROJECT_NAME,
        description="4B Medical Operating System",
        version=settings.PROJECT_VERSION,
        docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
        redoc_url=None if settings.ENVIRONMENT == "production" else "/redoc",
        openapi_url=None if settings.ENVIRONMENT == "production" else "/openapi.json",
    )

    @application.exception_handler(ClinicalWriteConflictError)
    async def clinical_write_conflict(request, error):
        return JSONResponse(status_code=409, content={"detail": str(error)})

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
