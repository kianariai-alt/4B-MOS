from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.app.api.router import api_router
from backend.app.core.config import settings
from backend.app.db.transactions import ClinicalWriteConflictError


CLINICAL_CONSOLE_DIRECTORY = Path(__file__).resolve().parent / "web"

CLINICAL_CONSOLE_CSP = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'none'",
        "connect-src 'self'",
        "font-src 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "img-src 'self' data:",
        "object-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
    )
)


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

    @application.middleware("http")
    async def secure_clinical_console(
        request: Request,
        call_next,
    ):
        response = await call_next(request)

        if request.url.path == "/app" or request.url.path.startswith("/app/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Content-Security-Policy"] = CLINICAL_CONSOLE_CSP
            response.headers["Permissions-Policy"] = (
                "camera=(), geolocation=(), microphone=()"
            )
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"

        return response

    application.include_router(
        api_router,
        prefix=settings.API_V1_PREFIX,
    )

    application.mount(
        "/app",
        StaticFiles(
            directory=CLINICAL_CONSOLE_DIRECTORY,
            html=True,
        ),
        name="clinical-console",
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
