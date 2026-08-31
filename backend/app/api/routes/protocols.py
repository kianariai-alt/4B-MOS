from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)

from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.schemas.protocol import (
    ProtocolCreate,
    ProtocolRead,
)
from backend.app.services.protocol import (
    ProtocolNotFoundError,
    ProtocolService,
    ProtocolVersionConflictError,
)


router = APIRouter(
    prefix="/protocols",
    tags=["Protocols"],
)


@router.post(
    "",
    response_model=ProtocolRead,
    status_code=status.HTTP_201_CREATED,
)
def create_protocol(
    payload: ProtocolCreate,
    db: Session = Depends(get_db),
) -> ProtocolRead:
    try:
        protocol = ProtocolService.create_protocol(
            db,
            payload,
        )

        return ProtocolRead.model_validate(
            protocol
        )

    except ProtocolVersionConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=list[ProtocolRead],
)
def list_protocols(
    treatment_type: str | None = Query(
        default=None,
    ),
    db: Session = Depends(get_db),
) -> list[ProtocolRead]:
    protocols = ProtocolService.list_protocols(
        db,
        treatment_type=treatment_type,
    )

    return [
        ProtocolRead.model_validate(protocol)
        for protocol in protocols
    ]


@router.get(
    "/{protocol_id}",
    response_model=ProtocolRead,
)
def get_protocol(
    protocol_id: str,
    db: Session = Depends(get_db),
) -> ProtocolRead:
    try:
        protocol = ProtocolService.get_protocol(
            db,
            protocol_id,
        )

        return ProtocolRead.model_validate(
            protocol
        )

    except ProtocolNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{protocol_id}",
    response_model=ProtocolRead,
)
def deactivate_protocol(
    protocol_id: str,
    db: Session = Depends(get_db),
) -> ProtocolRead:
    try:
        protocol = ProtocolService.deactivate_protocol(
            db,
            protocol_id,
        )

        return ProtocolRead.model_validate(
            protocol
        )

    except ProtocolNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc