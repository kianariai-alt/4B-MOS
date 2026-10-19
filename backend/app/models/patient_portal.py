"""Installation-scoped patient inbox. No implicit cross-clinic or legacy access."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.db.base import Base


def identifier():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc)


class PortalAccess(Base):
    __tablename__ = "portal_access"
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PortalSession(Base):
    __tablename__ = "portal_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PortalRequest(Base):
    __tablename__ = "portal_requests"
    __table_args__ = (
        UniqueConstraint("session_id", "request_key", name="uq_portal_session_request"),
        CheckConstraint("state IN ('submitted', 'linked', 'withdrawn')", name="ck_portal_request_state"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("portal_sessions.id", ondelete="RESTRICT"), index=True)
    request_key: Mapped[str] = mapped_column(String(100))
    receipt: Mapped[str] = mapped_column(String(30), unique=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    encrypted_content: Mapped[bytes] = mapped_column(LargeBinary)
    state: Mapped[str] = mapped_column(String(20), default="submitted")
    visit_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("visits.id", ondelete="RESTRICT"), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class PortalMessage(Base):
    __tablename__ = "portal_messages"
    __table_args__ = (UniqueConstraint("request_id", "request_key", name="uq_portal_message_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    request_id: Mapped[str] = mapped_column(String(36), ForeignKey("portal_requests.id", ondelete="RESTRICT"), index=True)
    request_key: Mapped[str] = mapped_column(String(100))
    author_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    encrypted_content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PortalAttachment(Base):
    __tablename__ = "portal_attachments"
    __table_args__ = (UniqueConstraint("request_id", "content_hash", name="uq_portal_attachment_hash"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    request_id: Mapped[str] = mapped_column(String(36), ForeignKey("portal_requests.id", ondelete="RESTRICT"), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    encrypted_content: Mapped[bytes] = mapped_column(LargeBinary)
    size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PortalThrottle(Base):
    __tablename__ = "portal_throttle"
    bucket: Mapped[str] = mapped_column(String(64), primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
