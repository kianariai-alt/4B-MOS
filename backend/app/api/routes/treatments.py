from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.treatment import (
    TreatmentCreate,
    TreatmentRead,
    TreatmentUpdate,
)
from backend.app.services.treatment import (
    TreatmentNotFoundError,
    TreatmentProtocolInactiveError,
    TreatmentProtocolMismatchError,
    TreatmentProtocolNotFoundError,
    TreatmentService,
    TreatmentVisitNotFoundError,
)


router = APIRouter(
    tags=["Treatments"],
)


READ_ROLES = (
    "admin",
    "physician",
    "nurse",
    "operator",
    "viewer",
)


WRITE_ROLES = (
    "admin",
    "physician",
)


@router.post(
    "/visits/{visit_id}/treatments",
    response_model=TreatmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_treatment(
    visit_id: str,
    payload: TreatmentCreate,
    _current_user: User = Depends(
        require_roles(*WRITE_ROLES)
    ),
    db: Session = Depends(get_db),
) -> TreatmentRead:
    try:
        treatment = TreatmentService.create_treatment(
            db,
            visit_id,
            payload,
        )

        return TreatmentRead.model_validate(
            treatment
        )

    except (
        TreatmentVisitNotFoundError,
        TreatmentProtocolNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except (
        TreatmentProtocolMismatchError,
        TreatmentProtocolInactiveError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "/visits/{visit_id}/treatments",
    response_model=list[TreatmentRead],
)
def list_visit_treatments(
    visit_id: str,
    skip: int = Query(
        default=0,
        ge=0,
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
    ),
    _current_user: User = Depends(
        require_roles(*READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> list[TreatmentRead]:
    try:
        treatments = (
            TreatmentService.list_visit_treatments(
                db,
                visit_id,
                skip=skip,
                limit=limit,
            )
        )

        return [
            TreatmentRead.model_validate(
                treatment
            )
            for treatment in treatments
        ]

    except TreatmentVisitNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/treatments/{treatment_id}",
    response_model=TreatmentRead,
)
def get_treatment(
    treatment_id: str,
    _current_user: User = Depends(
        require_roles(*READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> TreatmentRead:
    try:
        treatment = (
            TreatmentService.get_treatment(
                db,
                treatment_id,
            )
        )

        return TreatmentRead.model_validate(
            treatment
        )

    except TreatmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.patch(
    "/treatments/{treatment_id}",
    response_model=TreatmentRead,
)
def update_treatment(
    treatment_id: str,
    payload: TreatmentUpdate,
    _current_user: User = Depends(
        require_roles(*WRITE_ROLES)
    ),
    db: Session = Depends(get_db),
) -> TreatmentRead:
    try:
        treatment = (
            TreatmentService.update_treatment(
                db,
                treatment_id,
                payload,
            )
        )

        return TreatmentRead.model_validate(
            treatment
        )

    except TreatmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc