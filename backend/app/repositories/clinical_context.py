from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.models.clinical_context import (
    ClinicalIntake,
    ParaclinicalObservation,
    ParaclinicalReport,
)
from backend.app.schemas.clinical_context import (
    ClinicalIntakeContent,
    ParaclinicalObservationInput,
    ParaclinicalReportContent,
)


class ClinicalContextRepository:
    @staticmethod
    def get_intake_by_id(
        db: Session,
        intake_id: str,
        *,
        for_update: bool = False,
    ) -> ClinicalIntake | None:
        statement = select(ClinicalIntake).where(ClinicalIntake.id == intake_id)
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    @staticmethod
    def get_latest_intake(
        db: Session,
        visit_id: str,
        *,
        for_update: bool = False,
    ) -> ClinicalIntake | None:
        statement = (
            select(ClinicalIntake)
            .where(ClinicalIntake.visit_id == visit_id)
            .order_by(ClinicalIntake.version.desc())
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    @staticmethod
    def get_current_final_intake(
        db: Session,
        visit_id: str,
    ) -> ClinicalIntake | None:
        return db.scalar(
            select(ClinicalIntake)
            .where(
                ClinicalIntake.visit_id == visit_id,
                ClinicalIntake.status == "final",
            )
            .order_by(ClinicalIntake.version.desc())
            .limit(1)
        )

    @staticmethod
    def get_intake_successor(
        db: Session,
        intake_id: str,
    ) -> ClinicalIntake | None:
        return db.scalar(
            select(ClinicalIntake).where(
                ClinicalIntake.supersedes_intake_id == intake_id
            )
        )

    @staticmethod
    def list_intakes(
        db: Session,
        visit_id: str,
    ) -> list[ClinicalIntake]:
        return list(
            db.scalars(
                select(ClinicalIntake)
                .where(ClinicalIntake.visit_id == visit_id)
                .order_by(ClinicalIntake.version.desc())
            ).all()
        )

    @staticmethod
    def create_intake(
        db: Session,
        *,
        visit_id: str,
        version: int,
        content: ClinicalIntakeContent,
        content_sha256: str,
        created_by_user_id: str,
        supersedes_intake_id: str | None = None,
        revision_reason: str | None = None,
    ) -> ClinicalIntake:
        intake = ClinicalIntake(
            visit_id=visit_id,
            version=version,
            content_sha256=content_sha256,
            created_by_user_id=created_by_user_id,
            supersedes_intake_id=supersedes_intake_id,
            revision_reason=revision_reason,
            **content.model_dump(),
        )
        db.add(intake)
        db.flush()
        return intake

    @staticmethod
    def get_report_by_id(
        db: Session,
        report_id: str,
        *,
        for_update: bool = False,
    ) -> ParaclinicalReport | None:
        statement = (
            select(ParaclinicalReport)
            .options(selectinload(ParaclinicalReport.observations))
            .where(ParaclinicalReport.id == report_id)
        )
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    @staticmethod
    def get_latest_report(
        db: Session,
        *,
        visit_id: str,
        report_key: str,
        for_update: bool = False,
    ) -> ParaclinicalReport | None:
        statement = (
            select(ParaclinicalReport)
            .options(selectinload(ParaclinicalReport.observations))
            .where(
                ParaclinicalReport.visit_id == visit_id,
                ParaclinicalReport.report_key == report_key,
            )
            .order_by(ParaclinicalReport.version.desc())
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    @staticmethod
    def get_report_successor(
        db: Session,
        report_id: str,
    ) -> ParaclinicalReport | None:
        return db.scalar(
            select(ParaclinicalReport)
            .options(selectinload(ParaclinicalReport.observations))
            .where(ParaclinicalReport.supersedes_report_id == report_id)
        )

    @staticmethod
    def list_reports(
        db: Session,
        visit_id: str,
        *,
        report_key: str | None = None,
    ) -> list[ParaclinicalReport]:
        statement = (
            select(ParaclinicalReport)
            .options(selectinload(ParaclinicalReport.observations))
            .where(ParaclinicalReport.visit_id == visit_id)
            .order_by(
                ParaclinicalReport.report_key.asc(),
                ParaclinicalReport.version.desc(),
            )
        )
        if report_key is not None:
            statement = statement.where(
                ParaclinicalReport.report_key == report_key
            )
        return list(db.scalars(statement).all())

    @staticmethod
    def list_current_final_reports(
        db: Session,
        visit_id: str,
    ) -> list[ParaclinicalReport]:
        return list(
            db.scalars(
                select(ParaclinicalReport)
                .options(selectinload(ParaclinicalReport.observations))
                .where(
                    ParaclinicalReport.visit_id == visit_id,
                    ParaclinicalReport.status == "final",
                )
                .order_by(ParaclinicalReport.report_key.asc())
            ).all()
        )

    @staticmethod
    def create_report(
        db: Session,
        *,
        visit_id: str,
        report_key: str,
        version: int,
        content: ParaclinicalReportContent,
        content_sha256: str,
        created_by_user_id: str,
        supersedes_report_id: str | None = None,
        revision_reason: str | None = None,
    ) -> ParaclinicalReport:
        values = content.model_dump(exclude={"observations"})
        report = ParaclinicalReport(
            visit_id=visit_id,
            report_key=report_key,
            version=version,
            content_sha256=content_sha256,
            created_by_user_id=created_by_user_id,
            supersedes_report_id=supersedes_report_id,
            revision_reason=revision_reason,
            **values,
        )
        report.observations = ClinicalContextRepository._build_observations(
            content.observations
        )
        db.add(report)
        db.flush()
        return report

    @staticmethod
    def replace_observations(
        db: Session,
        report: ParaclinicalReport,
        observations: list[ParaclinicalObservationInput],
    ) -> None:
        report.observations.clear()
        db.flush()
        report.observations.extend(
            ClinicalContextRepository._build_observations(observations)
        )
        db.flush()

    @staticmethod
    def _build_observations(
        observations: list[ParaclinicalObservationInput],
    ) -> list[ParaclinicalObservation]:
        return [
            ParaclinicalObservation(
                sort_order=index,
                **observation.model_dump(),
            )
            for index, observation in enumerate(observations, start=1)
        ]
