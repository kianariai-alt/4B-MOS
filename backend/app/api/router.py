from fastapi import APIRouter

from backend.app.api.routes.audit_logs import (
    router as audit_logs_router,
)
from backend.app.api.routes.auth import (
    router as auth_router,
)
from backend.app.api.routes.health import (
    router as health_router,
)
from backend.app.api.routes.patient_timeline import (
    router as patient_timeline_router,
)
from backend.app.api.routes.patients import (
    router as patients_router,
)
from backend.app.api.routes.protocols import (
    router as protocols_router,
)
from backend.app.api.routes.treatment_sessions import (
    router as treatment_sessions_router,
)
from backend.app.api.routes.treatments import (
    router as treatments_router,
)
from backend.app.api.routes.users import (
    router as users_router,
)
from backend.app.api.routes.visits import (
    router as visits_router,
)


api_router = APIRouter()

api_router.include_router(
    health_router
)

api_router.include_router(
    auth_router
)

api_router.include_router(
    patients_router
)

api_router.include_router(
    visits_router
)

api_router.include_router(
    treatments_router
)

api_router.include_router(
    protocols_router
)

api_router.include_router(
    treatment_sessions_router
)

api_router.include_router(
    audit_logs_router
)

api_router.include_router(
    patient_timeline_router
)

api_router.include_router(
    users_router
)