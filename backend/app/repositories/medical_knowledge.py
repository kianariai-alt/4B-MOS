from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models.medical_knowledge import (
    MedicalKnowledgeFact,
    MedicalKnowledgeSource,
)
from backend.app.schemas.medical_knowledge import (
    KnowledgeFactContent,
    KnowledgeSourceCreate,
)


class MedicalKnowledgeRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        fact_id: str,
        *,
        for_update: bool = False,
    ) -> MedicalKnowledgeFact | None:
        statement = (
            select(MedicalKnowledgeFact)
            .options(selectinload(MedicalKnowledgeFact.sources))
            .where(MedicalKnowledgeFact.id == fact_id)
        )
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    @staticmethod
    def get_latest_by_key(
        db: Session,
        fact_key: str,
        *,
        for_update: bool = False,
    ) -> MedicalKnowledgeFact | None:
        statement = (
            select(MedicalKnowledgeFact)
            .options(selectinload(MedicalKnowledgeFact.sources))
            .where(MedicalKnowledgeFact.fact_key == fact_key)
            .order_by(MedicalKnowledgeFact.version.desc())
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    @staticmethod
    def list(
        db: Session,
        *,
        status: str | None = None,
        clinical_domain: str | None = None,
        therapy_type: str | None = None,
        fact_key: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[MedicalKnowledgeFact]:
        statement = (
            select(MedicalKnowledgeFact)
            .options(selectinload(MedicalKnowledgeFact.sources))
            .order_by(
                MedicalKnowledgeFact.fact_key.asc(),
                MedicalKnowledgeFact.version.desc(),
            )
            .offset(skip)
            .limit(limit)
        )
        if status is not None:
            statement = statement.where(
                MedicalKnowledgeFact.status == status
            )
        if clinical_domain is not None:
            statement = statement.where(
                func.lower(MedicalKnowledgeFact.clinical_domain)
                == clinical_domain.casefold()
            )
        if therapy_type is not None:
            statement = statement.where(
                MedicalKnowledgeFact.therapy_type == therapy_type
            )
        if fact_key is not None:
            statement = statement.where(
                MedicalKnowledgeFact.fact_key == fact_key
            )
        if search is not None:
            pattern = f"%{search.casefold()}%"
            statement = statement.where(
                or_(
                    func.lower(MedicalKnowledgeFact.title).like(pattern),
                    func.lower(MedicalKnowledgeFact.statement).like(pattern),
                    func.lower(MedicalKnowledgeFact.fact_key).like(pattern),
                )
            )
        return list(db.scalars(statement).all())

    @staticmethod
    def list_approved(
        db: Session,
        *,
        as_of: date,
        clinical_domain: str | None = None,
        therapy_type: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[MedicalKnowledgeFact]:
        statement = (
            select(MedicalKnowledgeFact)
            .options(selectinload(MedicalKnowledgeFact.sources))
            .where(
                MedicalKnowledgeFact.status == "approved",
                or_(
                    MedicalKnowledgeFact.valid_from.is_(None),
                    MedicalKnowledgeFact.valid_from <= as_of,
                ),
                or_(
                    MedicalKnowledgeFact.valid_to.is_(None),
                    MedicalKnowledgeFact.valid_to >= as_of,
                ),
            )
            .order_by(
                MedicalKnowledgeFact.fact_key.asc(),
                MedicalKnowledgeFact.version.desc(),
            )
            .offset(skip)
            .limit(limit)
        )
        if clinical_domain is not None:
            statement = statement.where(
                func.lower(MedicalKnowledgeFact.clinical_domain)
                == clinical_domain.casefold()
            )
        if therapy_type is not None:
            statement = statement.where(
                MedicalKnowledgeFact.therapy_type == therapy_type
            )
        if search is not None:
            pattern = f"%{search.casefold()}%"
            statement = statement.where(
                or_(
                    func.lower(MedicalKnowledgeFact.title).like(pattern),
                    func.lower(MedicalKnowledgeFact.statement).like(pattern),
                    func.lower(MedicalKnowledgeFact.fact_key).like(pattern),
                )
            )
        return list(db.scalars(statement).all())

    @staticmethod
    def create(
        db: Session,
        *,
        fact_key: str,
        version: int,
        content: KnowledgeFactContent,
        content_sha256: str,
        created_by_user_id: str,
        supersedes_fact_id: str | None = None,
    ) -> MedicalKnowledgeFact:
        fact = MedicalKnowledgeFact(
            fact_key=fact_key,
            version=version,
            title=content.title,
            statement=content.statement,
            clinical_domain=content.clinical_domain,
            therapy_type=content.therapy_type,
            population=content.population,
            indication=content.indication,
            contraindications=list(content.contraindications),
            evidence_grade=content.evidence_grade,
            valid_from=content.valid_from,
            valid_to=content.valid_to,
            content_sha256=content_sha256,
            created_by_user_id=created_by_user_id,
            supersedes_fact_id=supersedes_fact_id,
        )
        fact.sources = MedicalKnowledgeRepository._build_sources(
            content.sources
        )
        db.add(fact)
        db.flush()
        return fact

    @staticmethod
    def replace_sources(
        db: Session,
        fact: MedicalKnowledgeFact,
        sources: list[KnowledgeSourceCreate],
    ) -> None:
        fact.sources.clear()
        db.flush()
        fact.sources.extend(
            MedicalKnowledgeRepository._build_sources(sources)
        )

    @staticmethod
    def _build_sources(
        sources: list[KnowledgeSourceCreate],
    ) -> list[MedicalKnowledgeSource]:
        return [
            MedicalKnowledgeSource(
                sort_order=index,
                **source.model_dump(),
            )
            for index, source in enumerate(sources, start=1)
        ]
