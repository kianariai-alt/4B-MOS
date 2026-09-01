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
from backend.app.schemas.treatment_session_component import (
    TreatmentSessionComponentCreate,
    TreatmentSessionComponentRead,
    TreatmentSessionComponentUpdate,
)
from backend.app.services.treatment_session import (
    TreatmentSessionNotFoundError,
)
from backend.app.services.treatment_session_component import (
    TreatmentSessionComponentLockedError,
    TreatmentSessionComponentMaterialInactiveError,
    TreatmentSessionComponentMaterialNotFoundError,
    TreatmentSessionComponentNotFoundError,
    TreatmentSessionComponentPlanMismatchError,
    TreatmentSessionComponentPlanNotFoundError,
    TreatmentSessionComponentSequenceConflictError,
    TreatmentSessionComponentService,
    TreatmentSessionComponentTraceabilityError,
)


router = APIRouter(
    tags=[
        "Treatment Session Components",
    ],
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
    (
        "/treatment-sessions/"
        "{session_id}/components"
    ),
    response_model=(
        TreatmentSessionComponentRead
    ),
    status_code=(
        status.HTTP_201_CREATED
    ),
)
def create_session_component(
    session_id: str,
    payload: TreatmentSessionComponentCreate,
    current_user: User = Depends(
        require_roles(*WRITE_ROLES)
    ),
    db: Session = Depends(get_db),
) -> TreatmentSessionComponentRead:
    try:
        component = (
            TreatmentSessionComponentService
            .create_component(
                db,
                session_id,
                payload,
                actor=current_user,
            )
        )

        return (
            TreatmentSessionComponentRead
            .model_validate(component)
        )

    except (
        TreatmentSessionNotFoundError,
        TreatmentSessionComponentMaterialNotFoundError,
        TreatmentSessionComponentPlanNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    except (
        TreatmentSessionComponentMaterialInactiveError,
        TreatmentSessionComponentPlanMismatchError,
        TreatmentSessionComponentSequenceConflictError,
        TreatmentSessionComponentLockedError,
        TreatmentSessionComponentTraceabilityError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc


@router.get(
    (
        "/treatment-sessions/"
        "{session_id}/components"
    ),
    response_model=list[
        TreatmentSessionComponentRead
    ],
)
def list_session_components(
    session_id: str,
    _current_user: User = Depends(
        require_roles(*READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> list[TreatmentSessionComponentRead]:
    try:
        components = (
            TreatmentSessionComponentService
            .list_components(
                db,
                session_id,
            )
        )

        return [
            TreatmentSessionComponentRead
            .model_validate(component)
            for component in components
        ]

    except TreatmentSessionNotFoundError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc


@router.get(
    (
        "/treatment-sessions/"
        "{session_id}/components/"
        "{component_id}"
    ),
    response_model=(
        TreatmentSessionComponentRead
    ),
)
def get_session_component(
    session_id: str,
    component_id: str,
    _current_user: User = Depends(
        require_roles(*READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> TreatmentSessionComponentRead:
    try:
        component = (
            TreatmentSessionComponentService
            .get_component(
                db,
                session_id,
                component_id,
            )
        )

        return (
            TreatmentSessionComponentRead
            .model_validate(component)
        )

    except (
        TreatmentSessionNotFoundError,
        TreatmentSessionComponentNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc


@router.patch(
    (
        "/treatment-sessions/"
        "{session_id}/components/"
        "{component_id}"
    ),
    response_model=(
        TreatmentSessionComponentRead
    ),
)
def update_session_component(
    session_id: str,
    component_id: str,
    payload: TreatmentSessionComponentUpdate,
    current_user: User = Depends(
        require_roles(*WRITE_ROLES)
    ),
    db: Session = Depends(get_db),
) -> TreatmentSessionComponentRead:
    try:
        component = (
            TreatmentSessionComponentService
            .update_component(
                db,
                session_id,
                component_id,
                payload,
                actor=current_user,
            )
        )

        return (
            TreatmentSessionComponentRead
            .model_validate(component)
        )

    except (
        TreatmentSessionNotFoundError,
        TreatmentSessionComponentNotFoundError,
        TreatmentSessionComponentMaterialNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    except (
        TreatmentSessionComponentSequenceConflictError,
        TreatmentSessionComponentLockedError,
        TreatmentSessionComponentTraceabilityError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc


@router.delete(
    (
        "/treatment-sessions/"
        "{session_id}/components/"
        "{component_id}"
    ),
    status_code=(
        status.HTTP_204_NO_CONTENT
    ),
)
def delete_session_component(
    session_id: str,
    component_id: str,
    current_user: User = Depends(
        require_roles(*WRITE_ROLES)
    ),
    db: Session = Depends(get_db),
) -> Response:
    try:
        (
            TreatmentSessionComponentService
            .delete_component(
                db,
                session_id,
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
        TreatmentSessionNotFoundError,
        TreatmentSessionComponentNotFoundError,
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc

    except TreatmentSessionComponentLockedError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc
