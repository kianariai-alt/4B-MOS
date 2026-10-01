"""Immutable visit-scoped recording authorization and completion evidence."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.db.base import Base

class VisitRecordingEvent(Base):
    __tablename__ = "visit_recording_events"
    __table_args__ = (
        UniqueConstraint("visit_id", "version", name="uq_recording_visit_version"),
        UniqueConstraint("recording_id", "action", name="uq_recording_id_action"),
        UniqueConstraint("visit_id", "request_key", name="uq_recording_visit_request"),
        CheckConstraint("version > 0", name="ck_recording_version"),
        CheckConstraint("length(sha256) = 64", name="ck_recording_sha"),
        CheckConstraint("action IN ('start', 'finish')", name="ck_recording_action"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    visit_id: Mapped[str] = mapped_column(String(36), ForeignKey("visits.id", ondelete="RESTRICT"), index=True)
    recording_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))
    request_key: Mapped[str] = mapped_column(String(100))
    recorded_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    payload: Mapped[dict] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64))

def _immutable(mapper, connection, target):
    raise ValueError("Recording evidence is append-only.")

event.listen(VisitRecordingEvent, "before_update", _immutable)
event.listen(VisitRecordingEvent, "before_delete", _immutable)
