from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.core.config import settings
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.pilot_readiness import ControlledPilotReadinessRead
from backend.app.services.pilot_readiness import ControlledPilotReadinessService


router = APIRouter(tags=["System"])


@router.get(
    "/pilot-readiness",
    response_model=ControlledPilotReadinessRead,
)
def controlled_pilot_readiness(
    _actor: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> ControlledPilotReadinessRead:
    return ControlledPilotReadinessService.build(db, settings)
