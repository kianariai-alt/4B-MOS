from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from sqlalchemy.orm import Session

from backend.app.db.session import get_db

from backend.app.schemas.visit import (
    VisitCreate,
    VisitRead,
    VisitUpdate,
)

from backend.app.services.visit import (
    VisitNotFoundError,
    VisitPatientNotFoundError,
    VisitService,
)


router = APIRouter(
    tags=["Visits"],
)


@router.post(
    "/patients/{patient_id}/visits",
    response_model=VisitRead,
    status_code=status.HTTP_201_CREATED,
)
def create_visit(
    patient_id: str,
    payload: VisitCreate,
    db: Session = Depends(get_db),
) -> VisitRead:
    try:
        visit = VisitService.create_visit(
            db,
            patient_id,
            payload,
        )

        return VisitRead.model_validate(
            visit
        )

    except VisitPatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/patients/{patient_id}/visits",
    response_model=list[VisitRead],
)
def list_patient_visits(
    patient_id: str,
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
) -> list[VisitRead]:
    try:
        visits = VisitService.list_patient_visits(
            db,
            patient_id,
            skip=skip,
            limit=limit,
        )

        return [
            VisitRead.model_validate(visit)
            for visit in visits
        ]

    except VisitPatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/visits/{visit_id}",
    response_model=VisitRead,
)
def get_visit(
    visit_id: str,
    db: Session = Depends(get_db),
) -> VisitRead:
    try:
        visit = VisitService.get_visit(
            db,
            visit_id,
        )

        return VisitRead.model_validate(
            visit
        )

    except VisitNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.patch(
    "/visits/{visit_id}",
    response_model=VisitRead,
)
def update_visit(
    visit_id: str,
    payload: VisitUpdate,
    db: Session = Depends(get_db),
) -> VisitRead:
    try:
        visit = VisitService.update_visit(
            db,
            visit_id,
            payload,
        )

        return VisitRead.model_validate(
            visit
        )

    except VisitNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc