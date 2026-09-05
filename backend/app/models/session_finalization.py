"""Application-append-only completion evidence; not a digital signature."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, event
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class SessionFinalization(Base):
    __tablename__ = "session_finalizations"

    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("treatment_sessions.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)


@event.listens_for(SessionFinalization, "before_update")
@event.listens_for(SessionFinalization, "before_delete")
def reject_rewrite(mapper, connection, target):
    raise ValueError("Finalization evidence cannot be updated or deleted through the ORM.")
