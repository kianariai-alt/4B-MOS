"""Append-only administrative intake and purpose-specific consent evidence."""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.db.base import Base


class ReceptionRevision(Base):
    __tablename__ = "reception_revisions"
    __table_args__ = (
        UniqueConstraint("visit_id", "version", name="uq_reception_visit_version"),
        UniqueConstraint("visit_id", "request_key", name="uq_reception_visit_request"),
        CheckConstraint("version > 0", name="ck_reception_version"),
        CheckConstraint("length(sha256) = 64", name="ck_reception_sha"),
    )
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    visit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("visits.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(100))
    recorded_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    payload: Mapped[dict] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class VisitConsentEvent(Base):
    __tablename__ = "visit_consent_events"
    __table_args__ = (
        UniqueConstraint("visit_id", "version", name="uq_consent_visit_version"),
        UniqueConstraint("visit_id", "request_key", name="uq_consent_visit_request"),
        CheckConstraint("version > 0", name="ck_consent_version"),
        CheckConstraint("length(sha256) = 64", name="ck_consent_sha"),
    )
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    visit_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("visits.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(100))
    recorded_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT")
    )
    payload: Mapped[dict] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


def _immutable(mapper, connection, target):
    raise ValueError("Reception and consent evidence are append-only.")


for model in (ReceptionRevision, VisitConsentEvent):
    event.listen(model, "before_update", _immutable)
    event.listen(model, "before_delete", _immutable)
