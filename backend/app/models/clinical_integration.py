"""Immutable integration snapshots and independently authored physician reviews."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class ClinicalIntegrationRun(Base):
    __tablename__ = "clinical_integration_runs"
    __table_args__ = (
        UniqueConstraint("visit_id", "request_key", name="uq_integration_run_request"),
        CheckConstraint("length(result_sha256) = 64", name="ck_integration_result_hash"),
        CheckConstraint("length(request_sha256) = 64", name="ck_integration_request_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    visit_id: Mapped[str] = mapped_column(String(36), ForeignKey("visits.id", ondelete="RESTRICT"), index=True)
    request_key: Mapped[str] = mapped_column(String(100))
    request_sha256: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    result_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


class ClinicalIntegrationReview(Base):
    __tablename__ = "clinical_integration_reviews"
    __table_args__ = (
        UniqueConstraint("run_id", "request_key", name="uq_integration_review_request"),
        CheckConstraint("length(sha256) = 64", name="ck_integration_review_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_integration_runs.id", ondelete="RESTRICT"), index=True)
    request_key: Mapped[str] = mapped_column(String(100))
    physician_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


def _reject_rewrite(mapper, connection, target):
    raise ValueError("Integration records are append-only; create a new run or review.")


for _model in (ClinicalIntegrationRun, ClinicalIntegrationReview):
    event.listen(_model, "before_update", _reject_rewrite)
    event.listen(_model, "before_delete", _reject_rewrite)
