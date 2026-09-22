from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.clinical_learning_review import (
    ClinicalLearningReviewRead,
)
from backend.app.services.clinical_learning_review import (
    ClinicalLearningIntegrityError,
    ClinicalLearningReviewService,
)


router = APIRouter(tags=["Clinical Learning"])
READ_ROLES = ("admin", "physician")


@router.get(
    "/learning/review",
    response_model=ClinicalLearningReviewRead,
)
def get_clinical_learning_review(
    _actor: User = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
) -> ClinicalLearningReviewRead:
    try:
        return ClinicalLearningReviewService.get_review(db)
    except ClinicalLearningIntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
