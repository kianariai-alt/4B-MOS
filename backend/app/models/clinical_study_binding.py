"""Append-only study-to-visit binding evidence and physician review history."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class ClinicalStudyBinding(Base):
    __tablename__ = "clinical_study_bindings"
    __table_args__ = (
        UniqueConstraint("visit_id", "request_key", name="uq_study_binding_request"),
        UniqueConstraint("visit_id", "report_key", "revision", name="uq_study_binding_revision"),
        CheckConstraint("revision >= 1", name="ck_study_binding_revision"),
        CheckConstraint("length(request_sha256) = 64", name="ck_study_binding_request_hash"),
        CheckConstraint("length(sha256) = 64", name="ck_study_binding_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    visit_id: Mapped[str] = mapped_column(String(36), ForeignKey("visits.id", ondelete="RESTRICT"), index=True)
    report_id: Mapped[str] = mapped_column(String(36), ForeignKey("paraclinical_reports.id", ondelete="RESTRICT"))
    report_key: Mapped[str] = mapped_column(String(100))
    # A visit lock orders revisions without rewriting earlier study evidence.
    revision: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(100))
    request_sha256: Mapped[str] = mapped_column(String(64))
    created_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


class ClinicalStudyBindingReview(Base):
    __tablename__ = "clinical_study_binding_reviews"
    __table_args__ = (
        UniqueConstraint("binding_id", "sequence", name="uq_study_binding_review_sequence"),
        UniqueConstraint("binding_id", "request_key", name="uq_study_binding_review_request"),
        CheckConstraint("sequence >= 1", name="ck_study_binding_review_sequence"),
        CheckConstraint("length(sha256) = 64", name="ck_study_binding_review_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    binding_id: Mapped[str] = mapped_column(String(36), ForeignKey("clinical_study_bindings.id", ondelete="RESTRICT"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(100))
    physician_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)


def _reject_rewrite(mapper, connection, target):
    raise ValueError("Study binding records are append-only; create a new binding or review.")


# These ORM guards supplement read-time digest verification, not database grants.
for _model in (ClinicalStudyBinding, ClinicalStudyBindingReview):
    event.listen(_model, "before_update", _reject_rewrite)
    event.listen(_model, "before_delete", _reject_rewrite)
