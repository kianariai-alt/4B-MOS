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
from backend.app.schemas.patient import (
    PatientCreate,
    PatientRead,
    PatientUpdate,
)
from backend.app.services.patient import (
    PatientCodeConflictError,
    PatientNotFoundError,
    PatientService,
)


router = APIRouter(
    prefix="/patients",
    tags=["Patients"],
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
    "nurse",
    "operator",
)


@router.post(
    "",
    response_model=PatientRead,
    status_code=status.HTTP_201_CREATED,
)
def create_patient(
    payload: PatientCreate,
    _current_user: User = Depends(
        require_roles(*WRITE_ROLES)
    ),
    db: Session = Depends(get_db),
) -> PatientRead:
    try:
        patient = PatientService.create_patient(
            db,
            payload,
        )

        return PatientRead.model_validate(
            patient
        )

    except PatientCodeConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=list[PatientRead],
)
def list_patients(
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
) -> list[PatientRead]:
    patients = PatientService.list_patients(
        db,
        skip=skip,
        limit=limit,
    )

    return [
        PatientRead.model_validate(patient)
        for patient in patients
    ]


@router.get(
    "/{patient_id}",
    response_model=PatientRead,
)
def get_patient(
    patient_id: str,
    _current_user: User = Depends(
        require_roles(*READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> PatientRead:
    try:
        patient = PatientService.get_patient(
            db,
            patient_id,
        )

        return PatientRead.model_validate(
            patient
        )

    except PatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.patch(
    "/{patient_id}",
    response_model=PatientRead,
)
def update_patient(
    patient_id: str,
    payload: PatientUpdate,
    _current_user: User = Depends(
        require_roles(*WRITE_ROLES)
    ),
    db: Session = Depends(get_db),
) -> PatientRead:
    try:
        patient = PatientService.update_patient(
            db,
            patient_id,
            payload,
        )

        return PatientRead.model_validate(
            patient
        )

    except PatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{patient_id}",
    response_model=PatientRead,
)
def deactivate_patient(
    patient_id: str,
    _current_user: User = Depends(
        require_roles("admin")
    ),
    db: Session = Depends(get_db),
) -> PatientRead:
    try:
        patient = PatientService.deactivate_patient(
            db,
            patient_id,
        )

        return PatientRead.model_validate(
            patient
        )

    except PatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc