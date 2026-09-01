from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
)
from sqlalchemy.orm import Session

from backend.app.api.dependencies import (
    require_roles,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.treatment_component import (
    TreatmentComponentCreate,
    TreatmentComponentRead,
    TreatmentComponentUpdate,
)
from backend.app.services.treatment import (
    TreatmentNotFoundError,
)
from backend.app.services.treatment_component import (
    TreatmentComponentDuplicateMaterialError,
    TreatmentComponentLockedError,
    TreatmentComponentMaterialInactiveError,
    TreatmentComponentMaterialNotFoundError,
    TreatmentComponentNotFoundError,
    TreatmentComponentSequenceConflictError,
    TreatmentComponentService,
)


router = APIRouter(
    tags=["Treatment Components"],
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
    "/treatments/{treatment_id}/components",
    response_model=TreatmentComponentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_treatment_component(
    treatment_id: str,
    payload: TreatmentComponentCreate,
    current_user: User = Depends(
        require_roles(*WRITE_ROLES)
    ),
    db: Session = Depends(get_db),
) -> TreatmentComponentRead:
    try:
        component = (
            TreatmentComponentService
            .create_component(
                db,
                treatment_id,
                payload,
                actor=current_user,
            )
        )

        return (
            TreatmentComponentRead
            .model_validate(component)
        )

    except (
        TreatmentNotFoundError,
        TreatmentComponentMaterialNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    except (
        TreatmentComponentMaterialInactiveError,
        TreatmentComponentDuplicateMaterialError,
        TreatmentComponentSequenceConflictError,
        TreatmentComponentLockedError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc


@router.get(
    "/treatments/{treatment_id}/components",
    response_model=list[TreatmentComponentRead],
)
def list_treatment_components(
    treatment_id: str,
    _current_user: User = Depends(
        require_roles(*READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> list[TreatmentComponentRead]:
    try:
        components = (
            TreatmentComponentService
            .list_components(
                db,
                treatment_id,
            )
        )

        return [
            TreatmentComponentRead
            .model_validate(component)
            for component in components
        ]

    except TreatmentNotFoundError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc


@router.get(
    (
        "/treatments/{treatment_id}"
        "/components/{component_id}"
    ),
    response_model=TreatmentComponentRead,
)
def get_treatment_component(
    treatment_id: str,
    component_id: str,
    _current_user: User = Depends(
        require_roles(*READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> TreatmentComponentRead:
    try:
        component = (
            TreatmentComponentService
            .get_component(
                db,
                treatment_id,
                component_id,
            )
        )

        return (
            TreatmentComponentRead
            .model_validate(component)
        )

    except (
        TreatmentNotFoundError,
        TreatmentComponentNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc


@router.patch(
    (
        "/treatments/{treatment_id}"
        "/components/{component_id}"
    ),
    response_model=TreatmentComponentRead,
)
def update_treatment_component(
    treatment_id: str,
    component_id: str,
    payload: TreatmentComponentUpdate,
    current_user: User = Depends(
        require_roles(*WRITE_ROLES)
    ),
    db: Session = Depends(get_db),
) -> TreatmentComponentRead:
    try:
        component = (
            TreatmentComponentService
            .update_component(
                db,
                treatment_id,
                component_id,
                payload,
                actor=current_user,
            )
        )

        return (
            TreatmentComponentRead
            .model_validate(component)
        )

    except (
        TreatmentNotFoundError,
        TreatmentComponentNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    except (
        TreatmentComponentSequenceConflictError,
        TreatmentComponentLockedError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc


@router.delete(
    (
        "/treatments/{treatment_id}"
        "/components/{component_id}"
    ),
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_treatment_component(
    treatment_id: str,
    component_id: str,
    current_user: User = Depends(
        require_roles(*WRITE_ROLES)
    ),
    db: Session = Depends(get_db),
) -> Response:
    try:
        (
            TreatmentComponentService
            .delete_component(
                db,
                treatment_id,
                component_id,
                actor=current_user,
            )
        )

        return Response(
            status_code=(
                status.HTTP_204_NO_CONTENT
            )
        )

    except (
        TreatmentNotFoundError,
        TreatmentComponentNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    except TreatmentComponentLockedError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc
