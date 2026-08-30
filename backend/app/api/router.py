from fastapi import APIRouter

from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.patients import router as patients_router


api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(patients_router)