from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_user
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.auth import (
    AccessTokenResponse,
    LoginRequest,
)
from backend.app.schemas.user import UserRead
from backend.app.services.auth import (
    AuthService,
    InactiveUserError,
    InvalidCredentialsError,
)


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


@router.post(
    "/login",
    response_model=AccessTokenResponse,
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> AccessTokenResponse:
    try:
        user = AuthService.authenticate(
            db,
            username=payload.username,
            password=payload.password,
        )

    except (
        InvalidCredentialsError,
        InactiveUserError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    token = AuthService.create_token(
        user
    )

    return AccessTokenResponse(
        access_token=token,
    )


@router.get(
    "/me",
    response_model=UserRead,
)
def current_user(
    user: User = Depends(get_current_user),
) -> UserRead:
    return UserRead.model_validate(
        user
    )