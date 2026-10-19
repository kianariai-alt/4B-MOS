"""A single installation inbox; never a public view of legacy clinical records."""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.dependencies import get_current_user
from backend.app.core.config import settings
from backend.app.db.session import get_db
from backend.app.models.patient_portal import PortalAttachment, PortalRequest, PortalSession
from backend.app.schemas.patient_portal import PatientRequestCreate, PortalLinkCreate, PortalMessageCreate, PortalAnswerCreate
from backend.app.services import patient_portal as svc


class BoundedPortalRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            svc.enabled()
            # Request bodies never reach FastAPI's JSON parser unbounded.
            if request.method in {"POST", "PUT", "PATCH"}:
                limit = 5 * 1024 * 1024 if request.url.path.endswith("/attachments") else 64 * 1024
                parts, count = [], 0
                async for chunk in request.stream():
                    count += len(chunk)
                    if count > limit:
                        raise HTTPException(413, "حجم اطلاعات بیش از حد مجاز است.")
                    parts.append(chunk)
                request._body = b"".join(parts)
                if request.headers.get("origin") != settings.PATIENT_PORTAL_ORIGIN:
                    raise HTTPException(403, "درخواست باید از نشانی مجاز درگاه ارسال شود.")
            return await original(request)
        return handle


router = APIRouter(prefix="/patient-portal", tags=["Patient portal"], route_class=BoundedPortalRoute)
staff_router = APIRouter(prefix="/portal-staff", tags=["Patient inbox staff"], route_class=BoundedPortalRoute)


def patient_session(request: Request, db: Session = Depends(get_db)):
    session = svc.get_session(db, request.cookies.get(svc.COOKIE))
    if request.method != "GET":
        if not secrets.compare_digest(request.headers.get("x-portal-csrf", ""), session.csrf_token):
            raise HTTPException(403, "نشست نامعتبر است؛ صفحه را دوباره باز کنید.")
        svc.throttle(db, "session:" + session.id, 200)
    return session


def staff(actor=Depends(get_current_user), db: Session = Depends(get_db)):
    svc.staff_access(db, actor)
    return actor


@router.get("/info")
def info():
    return {"clinic_name": settings.PATIENT_PORTAL_NAME, "notice_version": svc.NOTICE_VERSION,
        "scope": "single_installation", "identity_verification": "staff_review",
        "upload_formats": ["image/jpeg", "image/png"], "max_upload_bytes": 5 * 1024 * 1024}


@router.post("/session")
def start(request: Request, response: Response, db: Session = Depends(get_db)):
    svc.throttle(db, "session-global", 500)
    svc.throttle(db, "session-ip:" + (request.client.host if request.client else "unknown"), 30)
    try:
        session = svc.get_session(db, request.cookies.get(svc.COOKIE))
    except HTTPException as error:
        if error.status_code != 401:
            raise
        token = secrets.token_urlsafe(32)
        session = PortalSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), csrf_token=secrets.token_hex(32),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=12))
        db.add(session)
        db.commit()
        response.set_cookie(svc.COOKIE, token, httponly=True, secure=settings.PATIENT_PORTAL_ORIGIN.startswith("https://"),
            samesite="strict", path=settings.API_V1_PREFIX + "/patient-portal", max_age=12 * 3600)
    rows = list(db.scalars(select(PortalRequest).where(PortalRequest.session_id == session.id).order_by(PortalRequest.created_at.desc())))
    return {"csrf_token": session.csrf_token, "expires_at": svc.utc(session.expires_at).isoformat(),
        "requests": [svc.receipt(row) for row in rows]}


@router.post("/logout")
def logout(response: Response, session=Depends(patient_session), db: Session = Depends(get_db)):
    session.expires_at = datetime.now(timezone.utc)
    db.commit()
    response.delete_cookie(svc.COOKIE, path=settings.API_V1_PREFIX + "/patient-portal")
    return {"closed": True}


@router.post("/requests", status_code=201)
def submit(payload: PatientRequestCreate, session=Depends(patient_session), db: Session = Depends(get_db)):
    return svc.submit(db, session, payload)


@router.get("/requests/{request_id}")
def view(request_id: str, session=Depends(patient_session), db: Session = Depends(get_db)):
    return svc.workspace(db, svc.owned(db, request_id, session))


@router.post("/requests/{request_id}/messages", status_code=201)
def reply(request_id: str, payload: PortalMessageCreate, session=Depends(patient_session), db: Session = Depends(get_db)):
    return svc.add_message(db, svc.owned(db, request_id, session), payload)


@router.post("/requests/{request_id}/interview-answers")
def interview_answer(request_id: str, payload: PortalAnswerCreate, session=Depends(patient_session), db: Session = Depends(get_db)):
    from backend.app.services.portal_interview import answer
    return answer(db, svc.owned(db, request_id, session), payload)


@router.post("/requests/{request_id}/attachments", status_code=201)
async def upload(request_id: str, request: Request, session=Depends(patient_session), db: Session = Depends(get_db)):
    from starlette.concurrency import run_in_threadpool
    row = svc.owned(db, request_id, session)
    svc.throttle(db, "uploads-global", 60)
    raw = await request.body()
    return await run_in_threadpool(svc.add_attachment, db, row, raw)


@router.post("/requests/{request_id}/withdraw")
def withdraw(request_id: str, session=Depends(patient_session), db: Session = Depends(get_db)):
    row = svc.owned(db, request_id, session)
    def command():
        svc.lock(db, PortalRequest, row.id)
        row.state = "withdrawn"
        svc.audit(db, row, "patient_withdrew")
        return svc.receipt(row)
    return svc.run_write(db, command)


@staff_router.get("/visits/{visit_id}/patient-report")
def visit_patient_report(visit_id: str, actor=Depends(staff), db: Session = Depends(get_db)):
    """Read the linked patient source without creating a clinical assertion."""
    row = db.scalar(select(PortalRequest).where(
        PortalRequest.visit_id == visit_id,
        PortalRequest.state == "linked",
    ).order_by(PortalRequest.created_at.desc(), PortalRequest.id).limit(1))
    return svc.workspace(db, row, actor) if row else None


@staff_router.get("/requests")
def inbox(limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0),
          actor=Depends(staff), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(PortalRequest).order_by(PortalRequest.created_at.desc(), PortalRequest.id).offset(offset).limit(limit)))
    # Queue has no medical free text; detail access is separately audited.
    return [svc.receipt(row) for row in rows]


@staff_router.get("/requests/{request_id}")
def staff_view(request_id: str, actor=Depends(staff), db: Session = Depends(get_db)):
    return svc.workspace(db, svc.owned(db, request_id), actor)


@staff_router.post("/requests/{request_id}/messages", status_code=201)
def question(request_id: str, payload: PortalMessageCreate, actor=Depends(staff), db: Session = Depends(get_db)):
    if actor.role not in {"physician", "admin"}:
        raise HTTPException(403, "پرسش تکمیلی بالینی باید توسط پزشک ارسال شود.")
    return svc.add_message(db, svc.owned(db, request_id), payload, actor)


@staff_router.post("/requests/{request_id}/accept")
def accept(request_id: str, payload: PortalLinkCreate, actor=Depends(staff), db: Session = Depends(get_db)):
    return svc.accept(db, svc.owned(db, request_id), payload, actor)


@staff_router.get("/requests/{request_id}/attachments/{attachment_id}")
def download(request_id: str, attachment_id: str, actor=Depends(staff), db: Session = Depends(get_db)):
    row = svc.owned(db, request_id)
    attachment = db.get(PortalAttachment, attachment_id)
    if attachment is None or attachment.request_id != row.id:
        raise HTTPException(404, "مدرک پیدا نشد.")
    raw = svc.decrypt(attachment.encrypted_content, "attachment:" + attachment.id)
    svc.audit(db, row, "staff_attachment_download", actor)
    db.commit()
    return Response(raw, media_type="image/png", headers={"Content-Disposition": 'attachment; filename="medical-image.png"'})
