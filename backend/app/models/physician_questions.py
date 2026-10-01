"""Append-only physician question bank lifecycle."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column
from backend.app.db.base import Base

class PhysicianQuestionEvent(Base):
    __tablename__ = "physician_question_events"
    __table_args__ = (
        UniqueConstraint("physician_id", "version", name="uq_question_owner_version"),
        UniqueConstraint("physician_id", "request_key", name="uq_question_owner_request"),
        CheckConstraint("version > 0", name="ck_question_version"),
        CheckConstraint("length(sha256) = 64", name="ck_question_sha"),
        CheckConstraint("action IN ('draft', 'approve', 'retire')", name="ck_question_action"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    physician_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", name="fk_question_owner", ondelete="RESTRICT"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(20))
    request_key: Mapped[str] = mapped_column(String(100))
    recorded_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", name="fk_question_recorder", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    payload: Mapped[dict] = mapped_column(JSON)
    sha256: Mapped[str] = mapped_column(String(64))

def _immutable(mapper, connection, target):
    raise ValueError("Physician question history is append-only.")

event.listen(PhysicianQuestionEvent, "before_update", _immutable)
event.listen(PhysicianQuestionEvent, "before_delete", _immutable)
