from fastapi import (
    APIRouter,
    Depends,
)
from sqlalchemy.orm import Session

from backend.app.api.dependencies import (
    require_roles,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.operations_dashboard import (
    OperationsDashboardResponse,
)
from backend.app.services.operations_dashboard import (
    OperationsDashboardService,
)


router = APIRouter(
    prefix="/dashboard",
    tags=["Operations Dashboard"],
)


DASHBOARD_ROLES = (
    "admin",
    "physician",
    "nurse",
    "operator",
)


@router.get(
    "/operations",
    response_model=(
        OperationsDashboardResponse
    ),
)
def get_operations_dashboard(
    _current_user: User = Depends(
        require_roles(
            *DASHBOARD_ROLES
        )
    ),
    db: Session = Depends(get_db),
) -> OperationsDashboardResponse:
    return (
        OperationsDashboardService
        .get_dashboard(
            db
        )
    )