from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.dependencies import (
    require_roles,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.clinic_live_flow import (
    ClinicLiveFlowResponse,
)
from backend.app.services.clinic_live_flow import (
    ClinicLiveFlowService,
)


router = APIRouter(
    prefix="/dashboard",
    tags=["Clinic Live Flow"],
)


LIVE_FLOW_ROLES = (
    "admin",
    "physician",
    "nurse",
    "operator",
)


@router.get(
    "/live-flow",
    response_model=ClinicLiveFlowResponse,
)
def get_clinic_live_flow(
    _current_user: User = Depends(
        require_roles(
            *LIVE_FLOW_ROLES
        )
    ),
    db: Session = Depends(get_db),
) -> ClinicLiveFlowResponse:
    return (
        ClinicLiveFlowService
        .get_live_flow(db)
    )