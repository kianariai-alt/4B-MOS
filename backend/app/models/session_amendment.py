"""Append-only amendments and reviews for captured session evidence."""

from __future__ import annotations

import uuid
from datetime import datetime

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


class SessionAmendment(Base):
    __tablename__ = "session_amendments"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "sequence",
            name="uq_session_amendments_session_sequence",
        ),
        CheckConstraint(
            "sequence >= 1",
            name="ck_session_amendments_sequence_positive",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "session_finalizations.session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )
    sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )


class SessionAmendmentReview(Base):
    __tablename__ = "session_amendment_reviews"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name="ck_session_amendment_reviews_decision",
        ),
    )

    amendment_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "session_amendments.id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    decision: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    payload: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )
    sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )


def _reject_amendment_rewrite(mapper, connection, target):
    raise ValueError(
        "Session amendments and reviews cannot be updated or deleted through the ORM."
    )


for _model in (SessionAmendment, SessionAmendmentReview):
    event.listen(_model, "before_update", _reject_amendment_rewrite)
    event.listen(_model, "before_delete", _reject_amendment_rewrite)
