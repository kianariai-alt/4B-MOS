"""Authenticated, consent-bound central transcript handoff and review."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import require_roles
from backend.app.db.account_transactions import AccountWriteConflictError
from backend.app.db.clinical_record_transactions import ClinicalRecordWriteConflictError
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.visit_learning import (
    VisitLearningBankPreview, VisitLearningPromote, VisitLearningPromotion,
    VisitLearningRead, VisitLearningReviewCommand, VisitLearningSubmit, VisitLearningSummary,
)
from backend.app.services.audio_crypto import AudioConfigurationError, AudioIntegrityError
from backend.app.services.physician_questions import QuestionBankAuthorizationError, QuestionBankConflictError
from backend.app.services.visit_learning import (
    VisitLearningService, VisitLearningAuthorizationError, VisitLearningConflictError, VisitLearningNotFoundError,
)
from backend.app.schemas.recording_inbox import RecordingInboxRead
from backend.app.schemas.interview_style import ApprovedInterviewStyle, PhysicianCopilotWithInterviewStyle
from backend.app.services.recording_inbox import list_recording_inbox
from backend.app.services.interview_style import approved_interview_style, copilot_with_interview_style
from backend.app.services.recording import RecordingAuthorizationError, RecordingConflictError, RecordingNotFoundError
from backend.app.services.recording_media import MediaAuthorizationError, MediaConflictError, MediaNotFoundError
from backend.app.services.reception import ReceptionConflictError, ReceptionNotFoundError
from backend.app.api.routes.physician_copilot import COPILOT_ERRORS, _translate_error


router = APIRouter(tags=["Visit Learning Handoff"])
MAX_PACKET_BYTES = 1024 * 1024


def call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (VisitLearningNotFoundError, RecordingNotFoundError, MediaNotFoundError, ReceptionNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc
    except (VisitLearningAuthorizationError, QuestionBankAuthorizationError, RecordingAuthorizationError, MediaAuthorizationError) as exc:
        raise HTTPException(403, str(exc)) from exc
    except (VisitLearningConflictError, QuestionBankConflictError, ClinicalRecordWriteConflictError,
            AccountWriteConflictError, AudioIntegrityError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except AudioConfigurationError as exc:
        raise HTTPException(503, "Encrypted transcript storage is not configured.") from exc
    except (RecordingConflictError, MediaConflictError, ReceptionConflictError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/recording-inbox", response_model=RecordingInboxRead)
def recording_inbox(response: Response, room_code: str | None = Query(default=None, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$"),
                    limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
                    actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return call(list_recording_inbox, db, actor=actor, room_code=room_code, limit=limit, offset=offset)


@router.get("/visits/{visit_id}/interview-style", response_model=ApprovedInterviewStyle)
def interview_style(visit_id: str, response: Response,
                    actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return call(approved_interview_style, db, visit_id, actor=actor)


@router.get("/visits/{visit_id}/physician-copilot/with-interview-style", response_model=PhysicianCopilotWithInterviewStyle)
def styled_copilot(visit_id: str, response: Response,
                   actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    try:
        return call(copilot_with_interview_style, db, visit_id, actor=actor)
    except COPILOT_ERRORS as exc:
        _translate_error(exc)


async def bounded_packet(request: Request) -> VisitLearningSubmit:
    if request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
        raise HTTPException(415, "A JSON transcript packet is required.")
    body = bytearray()
    try:
        async for part in request.stream():
            if len(body) + len(part) > MAX_PACKET_BYTES:
                raise HTTPException(413, "The transcript packet exceeds the 1 MiB limit.")
            body.extend(part)
        return VisitLearningSubmit.model_validate_json(bytes(body))
    except ValidationError as exc:
        # Do not echo transcript content in error payloads or logs.
        raise HTTPException(422, "Invalid transcript packet, review attestations, question spans or checksums.") from exc
    finally:
        body[:] = b"\0" * len(body)


@router.get("/visit-learning", response_model=list[VisitLearningSummary])
def list_packets(response: Response, room_code: str | None = Query(default=None, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$"),
                 limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0),
                 actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return call(VisitLearningService.list_for_physician, db, actor=actor, room_code=room_code, limit=limit, offset=offset)


@router.get("/visits/{visit_id}/visit-learning", response_model=list[VisitLearningSummary])
def list_visit_packets(visit_id: str, response: Response,
                      actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return call(VisitLearningService.list_for_visit, db, visit_id, actor=actor)


@router.post("/visits/{visit_id}/visit-learning", response_model=VisitLearningRead, status_code=201)
async def upload_packet(visit_id: str, request: Request, response: Response,
                        actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    command = await bounded_packet(request)
    return call(VisitLearningService.submit, db, visit_id, command, actor=actor)


@router.get("/visit-learning/{packet_id}", response_model=VisitLearningRead)
def read_packet(packet_id: str, response: Response,
                actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return call(VisitLearningService.read, db, packet_id, actor=actor)


@router.get("/visit-learning/{packet_id}/download")
def download_packet(packet_id: str, actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    result = call(VisitLearningService.read, db, packet_id, actor=actor)
    return Response(json.dumps(result.packet.model_dump(mode="json"), ensure_ascii=False),
                    media_type="application/json", headers={
                        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                        "Content-Disposition": f'attachment; filename="visit-learning-{result.summary.packet_id}.json"',
                    })


@router.get("/visit-learning/{packet_id}/bank-preview", response_model=VisitLearningBankPreview)
def bank_preview(packet_id: str, response: Response,
                 actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return call(VisitLearningService.preview_bank, db, packet_id, actor=actor)


@router.post("/visit-learning/{packet_id}/bank-draft", response_model=VisitLearningPromotion, status_code=201)
def bank_draft(packet_id: str, command: VisitLearningPromote, response: Response,
               actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return call(VisitLearningService.promote_to_bank_draft, db, packet_id, command, actor=actor)


@router.post("/visit-learning/{packet_id}/reject", response_model=VisitLearningSummary)
def reject_packet(packet_id: str, command: VisitLearningReviewCommand, response: Response,
                  actor: User = Depends(require_roles("physician")), db: Session = Depends(get_db)):
    response.headers["Cache-Control"] = "no-store"
    return call(VisitLearningService.reject, db, packet_id, command, actor=actor)
