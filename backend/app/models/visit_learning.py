"""Append-only encrypted source packets and interview-draft handoff events."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, LargeBinary, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class VisitLearningEvent(Base):
    __tablename__ = "visit_learning_events"
    __table_args__ = (
        UniqueConstraint("packet_id", "version", name="uq_visit_learning_packet_version"),
        UniqueConstraint("physician_id", "request_key", name="uq_visit_learning_owner_request"),
        CheckConstraint("version > 0", name="ck_visit_learning_version"),
        CheckConstraint("length(sha256) = 64", name="ck_visit_learning_sha"),
        CheckConstraint("action IN ('submit', 'bank_draft', 'reject')", name="ck_visit_learning_action"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    packet_id: Mapped[str] = mapped_column(String(36), index=True)
    visit_id: Mapped[str] = mapped_column(String(36), ForeignKey("visits.id", ondelete="RESTRICT"), index=True)
    physician_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    recording_id: Mapped[str] = mapped_column(String(36))
    room_code: Mapped[str] = mapped_column(String(80), index=True)
    device_id: Mapped[str] = mapped_column(String(36))
    client_session_id: Mapped[str] = mapped_column(String(36))
    source_type: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))
    request_key: Mapped[str] = mapped_column(String(100))
    recorded_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"))
    bank_event_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("physician_question_events.id", ondelete="RESTRICT"), nullable=True)
    key_id: Mapped[str] = mapped_column(String(80))
    encrypted_data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    payload: Mapped[dict] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def _immutable(mapper, connection, target):
    raise ValueError("Visit learning history is append-only.")


event.listen(VisitLearningEvent, "before_update", _immutable)
event.listen(VisitLearningEvent, "before_delete", _immutable)
