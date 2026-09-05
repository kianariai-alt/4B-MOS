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
from backend.app.db.account_transactions import AccountWriteConflictError, AccountAuthorizationError
from backend.app.models.user import User
from backend.app.schemas.user import (
    UserCreate,
    UserRead,
    UserUpdate,
)
from backend.app.services.user import (
    UsernameConflictError,
    UserNotFoundError,
    UserService,
)


router = APIRouter(
    prefix="/users",
    tags=["Users"],
    dependencies=[
        Depends(
            require_roles("admin")
        )
    ],
)


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
def create_user(
    payload: UserCreate,
    actor: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> UserRead:
    try:
        user = UserService.create_user(
            db,
            payload,
            actor=actor,
        )

        return UserRead.model_validate(
            user
        )

    except AccountAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (UsernameConflictError, AccountWriteConflictError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=list[UserRead],
)
def list_users(
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
) -> list[UserRead]:
    users = UserService.list_users(
        db,
        skip=skip,
        limit=limit,
    )

    return [
        UserRead.model_validate(user)
        for user in users
    ]


@router.get(
    "/{user_id}",
    response_model=UserRead,
)
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
) -> UserRead:
    try:
        user = UserService.get_user(
            db,
            user_id,
        )

        return UserRead.model_validate(
            user
        )

    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.patch(
    "/{user_id}",
    response_model=UserRead,
)
def update_user(
    user_id: str,
    payload: UserUpdate,
    actor: User = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
) -> UserRead:
    try:
        user = UserService.update_user(
            db,
            user_id,
            payload,
            actor=actor,
        )

        return UserRead.model_validate(
            user
        )

    except AccountAuthorizationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except AccountWriteConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
