from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from sqlalchemy.orm import Session

from backend.app.db.session import get_db

from backend.app.schemas.treatment import (
    TreatmentCreate,
    TreatmentRead,
    TreatmentUpdate,
)

from backend.app.services.treatment import (
    TreatmentNotFoundError,
    TreatmentService,
    TreatmentVisitNotFoundError,
)


router = APIRouter(
    tags=["Treatments"],
)


@router.post(
    "/visits/{visit_id}/treatments",
    response_model=TreatmentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_treatment(
    visit_id: str,
    payload: TreatmentCreate,
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

    except TreatmentVisitNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
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
    db: Session = Depends(get_db),
) -> list[TreatmentRead]:
    try:
        treatments = TreatmentService.list_visit_treatments(
            db,
            visit_id,
            skip=skip,
            limit=limit,
        )

        return [
            TreatmentRead.model_validate(treatment)
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
    db: Session = Depends(get_db),
) -> TreatmentRead:
    try:
        treatment = TreatmentService.get_treatment(
            db,
            treatment_id,
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
    db: Session = Depends(get_db),
) -> TreatmentRead:
    try:
        treatment = TreatmentService.update_treatment(
            db,
            treatment_id,
            payload,
        )

        return TreatmentRead.model_validate(
            treatment
        )

    except TreatmentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc