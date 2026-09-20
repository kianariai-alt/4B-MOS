from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.app.models.medical_knowledge import MedicalKnowledgeFact
from backend.app.models.audit_log import AuditLog
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.medical_knowledge import (
    MedicalKnowledgeRepository,
)
from backend.app.schemas.medical_knowledge import (
    KnowledgeFactContent,
    KnowledgeFactCreate,
    KnowledgeFactRead,
    KnowledgeFactReview,
    KnowledgeFactSupersede,
    KnowledgeFactUpdate,
    KnowledgeSourceCreate,
)
from backend.app.services.audit_context import actor_data


AUTHOR_ROLES = {"admin", "physician"}
REVIEW_ROLES = {"admin", "physician"}


class MedicalKnowledgeNotFoundError(Exception):
    pass


class MedicalKnowledgeConflictError(Exception):
    pass


class MedicalKnowledgeAuthorizationError(Exception):
    pass


class MedicalKnowledgeIntegrityError(Exception):
    pass


def _source_payload(source) -> dict:
    return {
        "source_type": source.source_type,
        "title": source.title,
        "citation": source.citation,
        "publisher": source.publisher,
        "url": source.url,
        "doi": source.doi,
        "publication_date": (
            source.publication_date.isoformat()
            if source.publication_date is not None
            else None
        ),
        "guideline_version": source.guideline_version,
        "accessed_at": source.accessed_at.isoformat(),
    }


def knowledge_content_digest(
    *,
    fact_key: str,
    version: int,
    content: KnowledgeFactContent,
) -> str:
    payload = {
        "schema_version": 1,
        "fact_key": fact_key,
        "version": version,
        "title": content.title,
        "statement": content.statement,
        "clinical_domain": content.clinical_domain,
        "therapy_type": content.therapy_type,
        "population": content.population,
        "indication": content.indication,
        "contraindications": list(content.contraindications),
        "evidence_grade": content.evidence_grade,
        "valid_from": (
            content.valid_from.isoformat()
            if content.valid_from is not None
            else None
        ),
        "valid_to": (
            content.valid_to.isoformat()
            if content.valid_to is not None
            else None
        ),
        "sources": [_source_payload(source) for source in content.sources],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class MedicalKnowledgeService:
    @staticmethod
    def _require_actor(
        actor: User | None,
        allowed_roles: set[str],
    ) -> User:
        if (
            actor is None
            or not actor.is_active
            or actor.role not in allowed_roles
        ):
            raise MedicalKnowledgeAuthorizationError(
                "The current role is not allowed to perform this knowledge action."
            )
        return actor

    @staticmethod
    def _content_from_record(
        fact: MedicalKnowledgeFact,
    ) -> KnowledgeFactContent:
        return KnowledgeFactContent(
            title=fact.title,
            statement=fact.statement,
            clinical_domain=fact.clinical_domain,
            therapy_type=fact.therapy_type,
            population=fact.population,
            indication=fact.indication,
            contraindications=list(fact.contraindications),
            evidence_grade=fact.evidence_grade,
            valid_from=fact.valid_from,
            valid_to=fact.valid_to,
            sources=[
                KnowledgeSourceCreate(
                    source_type=source.source_type,
                    title=source.title,
                    citation=source.citation,
                    publisher=source.publisher,
                    url=source.url,
                    doi=source.doi,
                    publication_date=source.publication_date,
                    guideline_version=source.guideline_version,
                    accessed_at=source.accessed_at,
                )
                for source in fact.sources
            ],
        )

    @staticmethod
    def _verify(fact: MedicalKnowledgeFact) -> None:
        content = MedicalKnowledgeService._content_from_record(fact)
        expected = knowledge_content_digest(
            fact_key=fact.fact_key,
            version=fact.version,
            content=content,
        )
        if expected != fact.content_sha256:
            raise MedicalKnowledgeIntegrityError(
                "Stored medical knowledge failed its integrity check."
            )

    @staticmethod
    def _to_read(fact: MedicalKnowledgeFact) -> KnowledgeFactRead:
        MedicalKnowledgeService._verify(fact)
        return KnowledgeFactRead.model_validate(fact)

    @staticmethod
    def _reload(db: Session, fact_id: str) -> MedicalKnowledgeFact:
        fact = MedicalKnowledgeRepository.get_by_id(db, fact_id)
        if fact is None:
            raise MedicalKnowledgeNotFoundError(
                f"Medical knowledge fact '{fact_id}' was not found."
            )
        return fact

    @staticmethod
    def _actor_authored_content(
        db: Session,
        fact: MedicalKnowledgeFact,
        actor: User,
    ) -> bool:
        if fact.created_by_user_id == actor.id:
            return True
        return any(
            event.actor_user_id == actor.id
            and event.event_type == "knowledge_fact_updated"
            for event in AuditLogRepository.list_by_entity(
                db,
                entity_type="medical_knowledge_fact",
                entity_id=fact.id,
            )
        )

    @staticmethod
    def _commit(db: Session) -> None:
        try:
            db.commit()
        except (IntegrityError, StaleDataError) as exc:
            db.rollback()
            raise MedicalKnowledgeConflictError(
                "The knowledge record conflicts with another write; reload and retry."
            ) from exc

    @staticmethod
    def create(
        db: Session,
        payload: KnowledgeFactCreate,
        *,
        actor: User | None,
    ) -> KnowledgeFactRead:
        actor = MedicalKnowledgeService._require_actor(actor, AUTHOR_ROLES)
        existing = MedicalKnowledgeRepository.get_latest_by_key(
            db,
            payload.fact_key,
        )
        if existing is not None:
            raise MedicalKnowledgeConflictError(
                f"Fact key '{payload.fact_key}' already exists; create a superseding version."
            )
        content = KnowledgeFactContent.model_validate(
            payload.model_dump(exclude={"fact_key"})
        )
        digest = knowledge_content_digest(
            fact_key=payload.fact_key,
            version=1,
            content=content,
        )
        try:
            fact = MedicalKnowledgeRepository.create(
                db,
                fact_key=payload.fact_key,
                version=1,
                content=content,
                content_sha256=digest,
                created_by_user_id=actor.id,
            )
            AuditLogRepository.create(
                db,
                commit=False,
                entity_type="medical_knowledge_fact",
                entity_id=fact.id,
                event_type="knowledge_fact_created",
                from_state=None,
                to_state="draft",
                message="Medical knowledge fact created as draft.",
                event_data={
                    "fact_key": fact.fact_key,
                    "version": fact.version,
                    "content_sha256": fact.content_sha256,
                },
                **actor_data(actor),
            )
            MedicalKnowledgeService._commit(db)
        except (IntegrityError, StaleDataError) as exc:
            db.rollback()
            raise MedicalKnowledgeConflictError(
                "The knowledge fact key or version already exists."
            ) from exc
        return MedicalKnowledgeService._to_read(
            MedicalKnowledgeService._reload(db, fact.id)
        )

    @staticmethod
    def get(db: Session, fact_id: str) -> KnowledgeFactRead:
        return MedicalKnowledgeService._to_read(
            MedicalKnowledgeService._reload(db, fact_id)
        )

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
    ) -> list[KnowledgeFactRead]:
        facts = MedicalKnowledgeRepository.list(
            db,
            status=status,
            clinical_domain=clinical_domain,
            therapy_type=therapy_type,
            fact_key=fact_key.upper() if fact_key is not None else None,
            search=search,
            skip=skip,
            limit=limit,
        )
        return [MedicalKnowledgeService._to_read(fact) for fact in facts]

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
    ) -> list[KnowledgeFactRead]:
        facts = MedicalKnowledgeRepository.list_approved(
            db,
            as_of=as_of,
            clinical_domain=clinical_domain,
            therapy_type=therapy_type,
            search=search,
            skip=skip,
            limit=limit,
        )
        return [MedicalKnowledgeService._to_read(fact) for fact in facts]

    @staticmethod
    def list_audit_logs(
        db: Session,
        fact_id: str,
    ) -> list[AuditLog]:
        fact = MedicalKnowledgeService._reload(db, fact_id)
        MedicalKnowledgeService._verify(fact)
        return AuditLogRepository.list_by_entity(
            db,
            entity_type="medical_knowledge_fact",
            entity_id=fact_id,
        )

    @staticmethod
    def update(
        db: Session,
        fact_id: str,
        payload: KnowledgeFactUpdate,
        *,
        actor: User | None,
    ) -> KnowledgeFactRead:
        actor = MedicalKnowledgeService._require_actor(actor, AUTHOR_ROLES)
        fact = MedicalKnowledgeRepository.get_by_id(
            db,
            fact_id,
            for_update=True,
        )
        if fact is None:
            raise MedicalKnowledgeNotFoundError(
                f"Medical knowledge fact '{fact_id}' was not found."
            )
        MedicalKnowledgeService._verify(fact)
        if fact.status not in {"draft", "rejected"}:
            raise MedicalKnowledgeConflictError(
                "Only draft or rejected knowledge facts can be edited."
            )
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return MedicalKnowledgeService._to_read(fact)
        current = MedicalKnowledgeService._content_from_record(fact).model_dump()
        current.update(changes)
        content = KnowledgeFactContent.model_validate(current)
        old_state = fact.status
        fact.title = content.title
        fact.statement = content.statement
        fact.clinical_domain = content.clinical_domain
        fact.therapy_type = content.therapy_type
        fact.population = content.population
        fact.indication = content.indication
        fact.contraindications = list(content.contraindications)
        fact.evidence_grade = content.evidence_grade
        fact.valid_from = content.valid_from
        fact.valid_to = content.valid_to
        try:
            if "sources" in changes:
                MedicalKnowledgeRepository.replace_sources(
                    db,
                    fact,
                    content.sources,
                )
            fact.content_sha256 = knowledge_content_digest(
                fact_key=fact.fact_key,
                version=fact.version,
                content=content,
            )
            fact.status = "draft"
            fact.submitted_at = None
            fact.reviewed_by_user_id = None
            fact.reviewed_at = None
            fact.review_comment = None
            AuditLogRepository.create(
                db,
                commit=False,
                entity_type="medical_knowledge_fact",
                entity_id=fact.id,
                event_type="knowledge_fact_updated",
                from_state=old_state,
                to_state="draft",
                message="Medical knowledge draft updated.",
                event_data={
                    "fact_key": fact.fact_key,
                    "version": fact.version,
                    "content_sha256": fact.content_sha256,
                },
                **actor_data(actor),
            )
            MedicalKnowledgeService._commit(db)
        except (IntegrityError, StaleDataError) as exc:
            db.rollback()
            raise MedicalKnowledgeConflictError(
                "The knowledge draft changed concurrently; reload and retry."
            ) from exc
        return MedicalKnowledgeService._to_read(
            MedicalKnowledgeService._reload(db, fact.id)
        )

    @staticmethod
    def submit(
        db: Session,
        fact_id: str,
        *,
        actor: User | None,
    ) -> KnowledgeFactRead:
        actor = MedicalKnowledgeService._require_actor(actor, AUTHOR_ROLES)
        fact = MedicalKnowledgeRepository.get_by_id(
            db,
            fact_id,
            for_update=True,
        )
        if fact is None:
            raise MedicalKnowledgeNotFoundError(
                f"Medical knowledge fact '{fact_id}' was not found."
            )
        MedicalKnowledgeService._verify(fact)
        if fact.status != "draft":
            raise MedicalKnowledgeConflictError(
                "Only a draft knowledge fact can be submitted for review."
            )
        fact.status = "in_review"
        fact.submitted_at = datetime.now(timezone.utc)
        try:
            AuditLogRepository.create(
                db,
                commit=False,
                entity_type="medical_knowledge_fact",
                entity_id=fact.id,
                event_type="knowledge_fact_submitted",
                from_state="draft",
                to_state="in_review",
                message="Medical knowledge fact submitted for clinical review.",
                event_data={
                    "fact_key": fact.fact_key,
                    "version": fact.version,
                    "content_sha256": fact.content_sha256,
                },
                **actor_data(actor),
            )
            MedicalKnowledgeService._commit(db)
        except (IntegrityError, StaleDataError) as exc:
            db.rollback()
            raise MedicalKnowledgeConflictError(
                "The knowledge draft changed concurrently; reload and retry."
            ) from exc
        return MedicalKnowledgeService._to_read(
            MedicalKnowledgeService._reload(db, fact.id)
        )

    @staticmethod
    def review(
        db: Session,
        fact_id: str,
        payload: KnowledgeFactReview,
        *,
        actor: User | None,
    ) -> KnowledgeFactRead:
        actor = MedicalKnowledgeService._require_actor(actor, REVIEW_ROLES)
        fact = MedicalKnowledgeRepository.get_by_id(
            db,
            fact_id,
            for_update=True,
        )
        if fact is None:
            raise MedicalKnowledgeNotFoundError(
                f"Medical knowledge fact '{fact_id}' was not found."
            )
        MedicalKnowledgeService._verify(fact)
        if fact.status != "in_review":
            raise MedicalKnowledgeConflictError(
                "Only a fact in review can receive a review decision."
            )
        if MedicalKnowledgeService._actor_authored_content(db, fact, actor):
            raise MedicalKnowledgeConflictError(
                "Medical knowledge requires an independent reviewer."
            )
        try:
            now = datetime.now(timezone.utc)
            if (
                payload.decision == "approved"
                and fact.supersedes_fact_id is not None
            ):
                previous = MedicalKnowledgeRepository.get_by_id(
                    db,
                    fact.supersedes_fact_id,
                    for_update=True,
                )
                if previous is None or previous.status != "approved":
                    raise MedicalKnowledgeConflictError(
                        "The superseded fact is no longer the approved version."
                    )
                MedicalKnowledgeService._verify(previous)
                previous.status = "retired"
                AuditLogRepository.create(
                    db,
                    commit=False,
                    entity_type="medical_knowledge_fact",
                    entity_id=previous.id,
                    event_type="knowledge_fact_superseded",
                    from_state="approved",
                    to_state="retired",
                    message=(
                        "Approved knowledge fact superseded by a new version."
                    ),
                    event_data={
                        "replacement_fact_id": fact.id,
                        "replacement_version": fact.version,
                    },
                    **actor_data(actor),
                )
            fact.status = payload.decision
            fact.reviewed_by_user_id = actor.id
            fact.reviewed_at = now
            fact.review_comment = payload.comment
            AuditLogRepository.create(
                db,
                commit=False,
                entity_type="medical_knowledge_fact",
                entity_id=fact.id,
                event_type=f"knowledge_fact_{payload.decision}",
                from_state="in_review",
                to_state=payload.decision,
                message=f"Medical knowledge fact {payload.decision}.",
                event_data={
                    "fact_key": fact.fact_key,
                    "version": fact.version,
                    "content_sha256": fact.content_sha256,
                    "comment": payload.comment,
                },
                **actor_data(actor),
            )
            MedicalKnowledgeService._commit(db)
        except (IntegrityError, StaleDataError) as exc:
            db.rollback()
            raise MedicalKnowledgeConflictError(
                "The knowledge review changed concurrently; reload and retry."
            ) from exc
        return MedicalKnowledgeService._to_read(
            MedicalKnowledgeService._reload(db, fact.id)
        )

    @staticmethod
    def supersede(
        db: Session,
        fact_id: str,
        payload: KnowledgeFactSupersede,
        *,
        actor: User | None,
    ) -> KnowledgeFactRead:
        actor = MedicalKnowledgeService._require_actor(actor, AUTHOR_ROLES)
        previous = MedicalKnowledgeRepository.get_by_id(
            db,
            fact_id,
            for_update=True,
        )
        if previous is None:
            raise MedicalKnowledgeNotFoundError(
                f"Medical knowledge fact '{fact_id}' was not found."
            )
        MedicalKnowledgeService._verify(previous)
        if previous.status != "approved":
            raise MedicalKnowledgeConflictError(
                "Only the approved knowledge version can be superseded."
            )
        latest = MedicalKnowledgeRepository.get_latest_by_key(
            db,
            previous.fact_key,
            for_update=True,
        )
        if latest is None or latest.id != previous.id:
            raise MedicalKnowledgeConflictError(
                "A newer version already exists for this fact key."
            )
        version = previous.version + 1
        content = KnowledgeFactContent.model_validate(payload.model_dump())
        digest = knowledge_content_digest(
            fact_key=previous.fact_key,
            version=version,
            content=content,
        )
        try:
            fact = MedicalKnowledgeRepository.create(
                db,
                fact_key=previous.fact_key,
                version=version,
                content=content,
                content_sha256=digest,
                created_by_user_id=actor.id,
                supersedes_fact_id=previous.id,
            )
            AuditLogRepository.create(
                db,
                commit=False,
                entity_type="medical_knowledge_fact",
                entity_id=fact.id,
                event_type="knowledge_fact_version_created",
                from_state=None,
                to_state="draft",
                message="Superseding medical knowledge version created as draft.",
                event_data={
                    "fact_key": fact.fact_key,
                    "version": fact.version,
                    "supersedes_fact_id": previous.id,
                    "content_sha256": fact.content_sha256,
                },
                **actor_data(actor),
            )
            MedicalKnowledgeService._commit(db)
        except (IntegrityError, StaleDataError) as exc:
            db.rollback()
            raise MedicalKnowledgeConflictError(
                "A newer knowledge version was created concurrently."
            ) from exc
        return MedicalKnowledgeService._to_read(
            MedicalKnowledgeService._reload(db, fact.id)
        )

    @staticmethod
    def retire(
        db: Session,
        fact_id: str,
        *,
        actor: User | None,
    ) -> KnowledgeFactRead:
        actor = MedicalKnowledgeService._require_actor(actor, REVIEW_ROLES)
        fact = MedicalKnowledgeRepository.get_by_id(
            db,
            fact_id,
            for_update=True,
        )
        if fact is None:
            raise MedicalKnowledgeNotFoundError(
                f"Medical knowledge fact '{fact_id}' was not found."
            )
        MedicalKnowledgeService._verify(fact)
        if fact.status != "approved":
            raise MedicalKnowledgeConflictError(
                "Only an approved knowledge fact can be retired."
            )
        fact.status = "retired"
        try:
            AuditLogRepository.create(
                db,
                commit=False,
                entity_type="medical_knowledge_fact",
                entity_id=fact.id,
                event_type="knowledge_fact_retired",
                from_state="approved",
                to_state="retired",
                message="Medical knowledge fact retired.",
                event_data={
                    "fact_key": fact.fact_key,
                    "version": fact.version,
                    "content_sha256": fact.content_sha256,
                },
                **actor_data(actor),
            )
            MedicalKnowledgeService._commit(db)
        except (IntegrityError, StaleDataError) as exc:
            db.rollback()
            raise MedicalKnowledgeConflictError(
                "The knowledge fact changed concurrently; reload and retry."
            ) from exc
        return MedicalKnowledgeService._to_read(
            MedicalKnowledgeService._reload(db, fact.id)
        )
