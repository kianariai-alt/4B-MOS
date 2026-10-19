"""Patient inbox commands, encrypted storage and explicit staff acceptance."""
import base64
import hashlib
import hmac
import io
import json
import secrets
import time
import warnings
from threading import BoundedSemaphore
from datetime import datetime, timezone

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError

from backend.app.core.config import settings
from backend.app.db.transactions import _is_contention
from backend.app.models.patient import Patient
from backend.app.models.visit import Visit
from backend.app.models.patient_portal import PortalAccess, PortalAttachment, PortalMessage, PortalRequest, PortalSession, PortalThrottle, identifier
from backend.app.models.reception import ReceptionRevision
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.schemas.reception import ReceptionCreate
from backend.app.services.audit_context import actor_data
from backend.app.services.reception import _record

NOTICE_VERSION = "portal-processing-v1"
COOKIE = "mos_patient_session"
CLINIC_SCOPE = "installation"
IMAGE_SLOTS = BoundedSemaphore(2)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def enabled():
    if not settings.PATIENT_PORTAL_ENABLED:
        raise HTTPException(404, "درگاه بیمار هنوز فعال نشده است.")


def _key():
    return base64.b64decode(settings.PATIENT_PORTAL_KEY.get_secret_value(), validate=True)


def digest(value):
    return hmac.new(_key(), value, hashlib.sha256).hexdigest()


def encrypt(value: bytes, aad: str):
    nonce = secrets.token_bytes(12)
    return nonce + AESGCM(_key()).encrypt(nonce, value, aad.encode())


def decrypt(value: bytes, aad: str):
    try:
        return AESGCM(_key()).decrypt(value[:12], value[12:], aad.encode())
    except InvalidTag as error:
        raise HTTPException(409, "یکپارچگی اطلاعات قابل تأیید نیست؛ با مدیر سامانه تماس بگیرید.") from error


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def content(row):
    return json.loads(decrypt(row.encrypted_content, "request:" + row.id))


def throttle(db, identity, limit=30):
    """Persistent atomic fixed windows; no raw IP or patient contact in storage."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    bucket = digest(f"{int(time.time()) // 300}:{identity}".encode())
    stmt = insert(PortalThrottle).values(bucket=bucket, count=1)
    stmt = stmt.on_conflict_do_update(index_elements=[PortalThrottle.bucket],
        set_={"count": PortalThrottle.count + 1}, where=PortalThrottle.count < limit).returning(PortalThrottle.count)
    result = db.execute(stmt).scalar_one_or_none()
    db.commit()
    if result is None:
        raise HTTPException(429, "درخواست‌ها زیاد است؛ چند دقیقه بعد دوباره تلاش کنید.", headers={"Retry-After": "300"})


def get_session(db, token):
    enabled()
    if not token or len(token) > 100:
        raise HTTPException(401, "نشست شما پایان یافته؛ صفحه را دوباره باز کنید.")
    session = db.scalar(select(PortalSession).where(PortalSession.token_hash == hashlib.sha256(token.encode()).hexdigest()))
    if session is None or utc(session.expires_at) <= datetime.now(timezone.utc):
        raise HTTPException(401, "نشست شما پایان یافته؛ صفحه را دوباره باز کنید.")
    return session


def staff_access(db, actor):
    enabled()
    grant = db.get(PortalAccess, actor.id)
    if not actor.is_active or actor.role not in {"admin", "operator", "physician"} or grant is None or not grant.active:
        raise HTTPException(403, "دسترسی شما به صندوق درخواست‌های بیمار فعال نیست.")


def owned(db, request_id, session=None):
    row = db.get(PortalRequest, request_id)
    if row is None or (session is not None and row.session_id != session.id):
        raise HTTPException(404, "درخواست پیدا نشد.")
    return row


def audit(db, row, action, actor=None):
    AuditLogRepository.create(db, entity_type="portal_request", entity_id=row.id,
        event_type=action, event_data={"scope": CLINIC_SCOPE}, commit=False, **actor_data(actor))


def receipt(row):
    return {"id": row.id, "receipt": row.receipt, "state": row.state, "created_at": utc(row.created_at).isoformat()}


def run_write(db, command):
    try:
        result = command()
        db.commit()
        return result
    except (IntegrityError, OperationalError) as error:
        db.rollback()
        if isinstance(error, IntegrityError) or _is_contention(error):
            raise HTTPException(409, "درخواست همزمان تغییر کرد؛ دوباره بارگذاری و تلاش کنید.") from error
        raise
    except Exception:
        db.rollback()
        raise


def lock(db, model, row_id):
    db.execute(update(model).where(model.id == row_id).values(id=model.id).execution_options(synchronize_session=False))
    db.expire_all()


def submit(db, session, payload):
    def command():
        lock(db, PortalSession, session.id)
        if utc(session.expires_at) <= datetime.now(timezone.utc):
            raise HTTPException(401, "نشست پایان یافته است.")
        data = payload.model_dump(mode="json")
        if data["processing_notice_version"] != NOTICE_VERSION:
            raise HTTPException(409, "متن رضایت تغییر کرده؛ صفحه را دوباره باز کنید.")
        raw = encode(data)
        previous = db.scalar(select(PortalRequest).where(PortalRequest.session_id == session.id, PortalRequest.request_key == payload.request_key))
        if previous:
            if previous.content_hash != digest(raw):
                raise HTTPException(409, "این شناسهٔ ارسال قبلاً برای اطلاعات دیگری استفاده شده است.")
            return receipt(previous)
        if db.scalar(select(func.count()).select_from(PortalRequest).where(PortalRequest.session_id == session.id)) >= 3:
            raise HTTPException(429, "سقف درخواست این نشست پر شده است.")
        row_id = identifier()
        row = PortalRequest(id=row_id, session_id=session.id, request_key=payload.request_key,
            receipt="MOS-" + secrets.token_hex(6).upper(), content_hash=digest(raw),
            encrypted_content=encrypt(raw, "request:" + row_id))
        db.add(row)
        db.flush()
        audit(db, row, "patient_submitted")
        return receipt(row)
    return run_write(db, command)


def workspace(db, row, actor=None):
    data = content(row)
    messages = list(db.scalars(select(PortalMessage).where(PortalMessage.request_id == row.id).order_by(PortalMessage.created_at, PortalMessage.id)))
    files = list(db.scalars(select(PortalAttachment).where(PortalAttachment.request_id == row.id).order_by(PortalAttachment.created_at)))
    result = {**receipt(row), "content": data, "identity_status": "unverified_patient_report",
        "visit_id": row.visit_id if actor else None,
        "messages": [{"id": m.id, "from": "clinician" if m.author_id else "patient", "text": decrypt(m.encrypted_content, "message:" + m.id).decode(), "created_at": utc(m.created_at).isoformat()} for m in messages],
        "attachments": [{"id": f.id, "size": f.size, "name": "مدرک تصویری " + str(i + 1)} for i, f in enumerate(files)],
        "missing_information": [label for field, label in (("medications", "داروهای مصرفی ثبت نشده‌اند"), ("allergies", "اطلاعات حساسیت ثبت نشده است"), ("conditions", "سوابق بیماری ثبت نشده است"), ("other_specialists", "پزشکان همکار مشخص نشده‌اند")) if not data.get(field)],
        "clinical_status": "اظهارات بیمار؛ نیازمند بررسی پزشک؛ فاقد تشخیص و مجوز درمان"}
    if actor:
        audit(db, row, "staff_viewed", actor)
        db.commit()
    return result


def add_message(db, row, payload, actor=None):
    def command():
        lock(db, PortalRequest, row.id)
        if row.state == "withdrawn":
            raise HTTPException(409, "درخواست بسته شده است.")
        author = actor.id if actor else None
        previous = db.scalar(select(PortalMessage).where(PortalMessage.request_id == row.id, PortalMessage.request_key == payload.request_key))
        if previous:
            if previous.author_id != author or decrypt(previous.encrypted_content, "message:" + previous.id).decode() != payload.text:
                raise HTTPException(409, "شناسهٔ پیام تکراری با محتوای متفاوت است.")
            return {"id": previous.id}
        if db.scalar(select(func.count()).select_from(PortalMessage).where(PortalMessage.request_id == row.id)) >= 100:
            raise HTTPException(409, "سقف پیام‌های این درخواست پر شده است.")
        mid = identifier()
        db.add(PortalMessage(id=mid, request_id=row.id, request_key=payload.request_key,
            author_id=author, encrypted_content=encrypt(payload.text.encode(), "message:" + mid)))
        audit(db, row, "clinician_question" if actor else "patient_reply", actor)
        return {"id": mid}
    return run_write(db, command)


def normalize_image(raw):
    """Decode and rewrite JPEG/PNG; never publish untrusted uploaded bytes."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"PNG", "JPEG"} or source.width * source.height > 16_000_000:
                    raise ValueError("Unsupported image.")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGB")
                target = io.BytesIO()
                image.save(target, format="PNG")
                value = target.getvalue()
                if len(value) > 8 * 1024 * 1024:
                    raise ValueError("Image is too large.")
                return value
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError) as error:
        raise HTTPException(422, "فقط تصویر سالم JPG یا PNG تا ۱۶ میلیون پیکسل پذیرفته می‌شود.") from error


def add_attachment(db, row, raw):
    if not IMAGE_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "سامانه در حال پردازش مدارک است؛ کمی بعد تلاش کنید.")
    try:
        clean = normalize_image(raw)
    finally:
        IMAGE_SLOTS.release()
    def command():
        lock(db, PortalRequest, row.id)
        if row.state == "withdrawn":
            raise HTTPException(409, "درخواست بسته شده است.")
        checksum = digest(clean)
        previous = db.scalar(select(PortalAttachment).where(PortalAttachment.request_id == row.id, PortalAttachment.content_hash == checksum))
        if previous:
            return {"id": previous.id}
        if db.scalar(select(func.count()).select_from(PortalAttachment).where(PortalAttachment.request_id == row.id)) >= 10:
            raise HTTPException(409, "حداکثر ۱۰ تصویر برای هر درخواست مجاز است.")
        fid = identifier()
        db.add(PortalAttachment(id=fid, request_id=row.id, content_hash=checksum,
            encrypted_content=encrypt(clean, "attachment:" + fid), size=len(clean)))
        audit(db, row, "patient_attachment")
        return {"id": fid}
    return run_write(db, command)


def accept(db, row, payload, actor):
    def command():
        lock(db, PortalRequest, row.id)
        staff_access(db, actor)
        if row.state == "withdrawn":
            raise HTTPException(409, "درخواست پس گرفته شده است.")
        if row.visit_id:
            linked = db.get(Visit, row.visit_id)
            if payload.existing_patient_id and linked.patient_id != payload.existing_patient_id:
                raise HTTPException(409, "درخواست به پروندهٔ دیگری متصل است.")
            return {"visit_id": row.visit_id, "patient_id": linked.patient_id}
        data = content(row)
        if payload.existing_patient_id:
            patient = db.get(Patient, payload.existing_patient_id)
            if patient is None or not patient.is_active:
                raise HTTPException(404, "پروندهٔ فعال بیمار پیدا نشد.")
        else:
            patient = Patient(patient_code="PORTAL-" + row.id, first_name=data["first_name"],
                last_name=data["last_name"], date_of_birth=date_from(data.get("date_of_birth")))
            db.add(patient)
            db.flush()
        visit = Visit(patient_id=patient.id, chief_complaint=data["complaint"][:2000], body_region=data.get("body_region"))
        db.add(visit)
        db.flush()
        command = ReceptionCreate(patient_reported_complaint=data["complaint"], phone=data.get("contact_phone"),
            expected_version=0, request_key="portal-" + row.id)
        _record(db, ReceptionRevision, visit.id, command, actor, [])
        row.visit_id = visit.id
        row.state = "linked"
        audit(db, row, "staff_identity_checked_and_linked", actor)
        # Portal consent is for processing this submission, not treatment/audio.
        return {"visit_id": visit.id, "patient_id": patient.id}
    return run_write(db, command)


def date_from(value):
    from datetime import date
    return date.fromisoformat(value) if value else None
