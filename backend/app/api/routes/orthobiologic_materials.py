from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from backend.app.api.dependencies import (
    require_roles,
)
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.orthobiologic_material import (
    OrthobiologicMaterialCreate,
    OrthobiologicMaterialRead,
)
from backend.app.services.orthobiologic_material import (
    OrthobiologicMaterialCodeConflictError,
    OrthobiologicMaterialNotFoundError,
    OrthobiologicMaterialService,
)


router = APIRouter(
    prefix="/orthobiologic-materials",
    tags=["Orthobiologic Materials"],
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
)


@router.post(
    "",
    response_model=OrthobiologicMaterialRead,
    status_code=status.HTTP_201_CREATED,
)
def create_material(
    payload: OrthobiologicMaterialCreate,
    current_user: User = Depends(
        require_roles(*WRITE_ROLES)
    ),
    db: Session = Depends(get_db),
) -> OrthobiologicMaterialRead:
    try:
        material = (
            OrthobiologicMaterialService
            .create_material(
                db,
                payload,
                actor=current_user,
            )
        )

        return (
            OrthobiologicMaterialRead
            .model_validate(material)
        )

    except (
        OrthobiologicMaterialCodeConflictError
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=list[
        OrthobiologicMaterialRead
    ],
)
def list_materials(
    active_only: bool = Query(
        default=True,
    ),
    category: str | None = Query(
        default=None,
    ),
    _current_user: User = Depends(
        require_roles(*READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> list[OrthobiologicMaterialRead]:
    materials = (
        OrthobiologicMaterialService
        .list_materials(
            db,
            active_only=active_only,
            category=category,
        )
    )

    return [
        OrthobiologicMaterialRead
        .model_validate(material)
        for material in materials
    ]


@router.get(
    "/{material_id}",
    response_model=OrthobiologicMaterialRead,
)
def get_material(
    material_id: str,
    _current_user: User = Depends(
        require_roles(*READ_ROLES)
    ),
    db: Session = Depends(get_db),
) -> OrthobiologicMaterialRead:
    try:
        material = (
            OrthobiologicMaterialService
            .get_material(
                db,
                material_id,
            )
        )

        return (
            OrthobiologicMaterialRead
            .model_validate(material)
        )

    except (
        OrthobiologicMaterialNotFoundError
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc


@router.delete(
    "/{material_id}",
    response_model=OrthobiologicMaterialRead,
)
def deactivate_material(
    material_id: str,
    current_user: User = Depends(
        require_roles(*WRITE_ROLES)
    ),
    db: Session = Depends(get_db),
) -> OrthobiologicMaterialRead:
    try:
        material = (
            OrthobiologicMaterialService
            .deactivate_material(
                db,
                material_id,
                actor=current_user,
            )
        )

        return (
            OrthobiologicMaterialRead
            .model_validate(material)
        )

    except (
        OrthobiologicMaterialNotFoundError
    ) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),
            detail=str(exc),
        ) from exc
