from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from backend.app.db.clinical_record_transactions import clinical_record_write
from backend.app.models.audit_log import AuditLog
from backend.app.models.clinical_safety import (
    ClinicalSafetyEvaluation,
    ClinicalSafetyRule,
)
from backend.app.models.user import User
from backend.app.repositories.audit_log import AuditLogRepository
from backend.app.repositories.clinical_safety import (
    ClinicalSafetyEvaluationRepository,
    ClinicalSafetyRuleRepository,
)
from backend.app.repositories.visit import VisitRepository
from backend.app.schemas.clinical_context import ClinicalContextRead
from backend.app.schemas.clinical_safety import (
    SafetyCondition,
    SafetyConditionTrace,
    SafetyEvaluationRead,
    SafetyEvaluationRequest,
    SafetyRuleContent,
    SafetyRuleCreate,
    SafetyRuleRead,
    SafetyRuleReview,
    SafetyRuleSupersede,
    SafetyRuleUpdate,
)
from backend.app.services.audit_context import actor_data
from backend.app.services.clinical_context import ClinicalContextService
from backend.app.services.medical_knowledge import (
    MedicalKnowledgeIntegrityError,
    MedicalKnowledgeNotFoundError,
    MedicalKnowledgeService,
)


ENGINE_VERSION = "1.0"
AUTHOR_ROLES = {"admin", "physician"}
REVIEW_ROLES = {"admin", "physician"}
EVALUATE_ROLES = {"admin", "physician"}
SEVERITY_ORDER = {"info": 0, "warning": 1, "high": 2, "critical": 3}


class ClinicalSafetyNotFoundError(Exception):
    pass


class ClinicalSafetyConflictError(Exception):
    pass


class ClinicalSafetyAuthorizationError(Exception):
    pass


class ClinicalSafetyIntegrityError(Exception):
    pass


class ClinicalSafetyRuleUnavailableError(Exception):
    pass


def _canonical_digest(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def safety_rule_content_digest(
    *,
    rule_key: str,
    version: int,
    content: SafetyRuleContent,
    knowledge_facts: list[tuple[str, str]],
) -> str:
    return _canonical_digest(
        {
            "schema_version": 1,
            "rule_key": rule_key,
            "version": version,
            "title": content.title,
            "description": content.description,
            "clinical_domain": content.clinical_domain,
            "severity": content.severity,
            "action": content.action,
            "message": content.message,
            "predicate": content.predicate.model_dump(mode="json"),
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
            "knowledge_facts": [
                {"id": fact_id, "content_sha256": content_sha256}
                for fact_id, content_sha256 in knowledge_facts
            ],
        }
    )


def clinical_context_digest(context: ClinicalContextRead) -> str:
    return _canonical_digest(
        {
            "schema_version": 1,
            "visit_id": context.visit_id,
            "intake": (
                {
                    "id": context.intake.id,
                    "content_sha256": context.intake.content_sha256,
                }
                if context.intake is not None
                else None
            ),
            "reports": [
                {
                    "id": report.id,
                    "report_key": report.report_key,
                    "content_sha256": report.content_sha256,
                }
                for report in context.reports
            ],
        }
    )


def safety_rule_set_digest(rules: list[ClinicalSafetyRule]) -> str:
    return _canonical_digest(
        {
            "schema_version": 1,
            "engine_version": ENGINE_VERSION,
            "rules": [
                {
                    "id": rule.id,
                    "rule_key": rule.rule_key,
                    "version": rule.version,
                    "content_sha256": rule.content_sha256,
                }
                for rule in rules
            ],
        }
    )


def safety_result_digest(
    *,
    evaluation_id: str,
    visit_id: str,
    intake_id: str | None,
    report_ids: list[str],
    outcome: str,
    evaluated_rule_count: int,
    triggered_count: int,
    highest_severity: str | None,
    clinical_context_sha256: str,
    rule_set_sha256: str,
    evaluated_by_user_id: str,
    findings: list[dict],
) -> str:
    return _canonical_digest(
        {
            "schema_version": 1,
            "engine_version": ENGINE_VERSION,
            "evaluation_id": evaluation_id,
            "visit_id": visit_id,
            "intake_id": intake_id,
            "report_ids": report_ids,
            "outcome": outcome,
            "evaluated_rule_count": evaluated_rule_count,
            "triggered_count": triggered_count,
            "highest_severity": highest_severity,
            "clinical_context_sha256": clinical_context_sha256,
            "rule_set_sha256": rule_set_sha256,
            "evaluated_by_user_id": evaluated_by_user_id,
            "findings": findings,
        }
    )


class ClinicalSafetyRuleService:
    @staticmethod
    def _require_actor(actor: User | None, allowed_roles: set[str]) -> User:
        if actor is None or not actor.is_active or actor.role not in allowed_roles:
            raise ClinicalSafetyAuthorizationError(
                "The current role is not allowed to perform this safety action."
            )
        return actor

    @staticmethod
    def _content_from_rule(rule: ClinicalSafetyRule) -> SafetyRuleContent:
        return SafetyRuleContent(
            title=rule.title,
            description=rule.description,
            clinical_domain=rule.clinical_domain,
            severity=rule.severity,
            action=rule.action,
            message=rule.message,
            predicate=rule.predicate,
            knowledge_fact_ids=[
                link.medical_knowledge_fact_id for link in rule.knowledge_links
            ],
            valid_from=rule.valid_from,
            valid_to=rule.valid_to,
        )

    @staticmethod
    def _knowledge_snapshot(rule: ClinicalSafetyRule) -> list[tuple[str, str]]:
        return [
            (link.medical_knowledge_fact_id, link.fact_content_sha256)
            for link in rule.knowledge_links
        ]

    @staticmethod
    def _verify(db: Session, rule: ClinicalSafetyRule) -> None:
        content = ClinicalSafetyRuleService._content_from_rule(rule)
        knowledge_facts = ClinicalSafetyRuleService._knowledge_snapshot(rule)
        expected = safety_rule_content_digest(
            rule_key=rule.rule_key,
            version=rule.version,
            content=content,
            knowledge_facts=knowledge_facts,
        )
        if expected != rule.content_sha256:
            raise ClinicalSafetyIntegrityError(
                "Stored clinical safety rule failed its integrity check."
            )
        for fact_id, snapshot_hash in knowledge_facts:
            try:
                fact = MedicalKnowledgeService.get(db, fact_id)
            except (
                MedicalKnowledgeNotFoundError,
                MedicalKnowledgeIntegrityError,
            ) as error:
                raise ClinicalSafetyIntegrityError(
                    "A linked medical knowledge fact could not be verified."
                ) from error
            if fact.content_sha256 != snapshot_hash:
                raise ClinicalSafetyIntegrityError(
                    "A safety rule knowledge link failed its integrity check."
                )

    @staticmethod
    def _to_read(db: Session, rule: ClinicalSafetyRule) -> SafetyRuleRead:
        ClinicalSafetyRuleService._verify(db, rule)
        return SafetyRuleRead.model_validate(rule)

    @staticmethod
    def _reload(db: Session, rule_id: str) -> ClinicalSafetyRule:
        rule = ClinicalSafetyRuleRepository.get_by_id(db, rule_id)
        if rule is None:
            raise ClinicalSafetyNotFoundError(
                f"Clinical safety rule '{rule_id}' was not found."
            )
        return rule

    @staticmethod
    def _active_knowledge_facts(
        db: Session,
        fact_ids: list[str],
        *,
        as_of: date,
        unavailable_error: bool = False,
        for_share: bool = False,
    ) -> list[tuple[str, str]]:
        facts: list[tuple[str, str]] = []
        for fact_id in fact_ids:
            try:
                fact = MedicalKnowledgeService.get(
                    db,
                    fact_id,
                    for_share=for_share,
                )
            except MedicalKnowledgeNotFoundError as error:
                exception = (
                    ClinicalSafetyRuleUnavailableError
                    if unavailable_error
                    else ClinicalSafetyConflictError
                )
                raise exception(
                    f"Medical knowledge fact '{fact_id}' is unavailable."
                ) from error
            except MedicalKnowledgeIntegrityError as error:
                raise ClinicalSafetyIntegrityError(
                    "A linked medical knowledge fact failed its integrity check."
                ) from error
            is_current = (
                fact.status == "approved"
                and (fact.valid_from is None or fact.valid_from <= as_of)
                and (fact.valid_to is None or fact.valid_to >= as_of)
            )
            if not is_current:
                exception = (
                    ClinicalSafetyRuleUnavailableError
                    if unavailable_error
                    else ClinicalSafetyConflictError
                )
                raise exception(
                    "Every safety rule must reference approved, currently valid "
                    f"medical knowledge; '{fact_id}' is not current."
                )
            facts.append((fact.id, fact.content_sha256))
        return facts

    @staticmethod
    def _actor_authored_content(
        db: Session,
        rule: ClinicalSafetyRule,
        actor: User,
    ) -> bool:
        if rule.created_by_user_id == actor.id:
            return True
        return any(
            event.actor_user_id == actor.id
            and event.event_type == "clinical_safety_rule_updated"
            for event in AuditLogRepository.list_by_entity(
                db,
                entity_type="clinical_safety_rule",
                entity_id=rule.id,
            )
        )

    @staticmethod
    def _commit(db: Session) -> None:
        try:
            db.commit()
        except (IntegrityError, StaleDataError) as error:
            db.rollback()
            raise ClinicalSafetyConflictError(
                "The safety record conflicts with another write; reload and retry."
            ) from error

    @staticmethod
    def create(
        db: Session,
        payload: SafetyRuleCreate,
        *,
        actor: User | None,
    ) -> SafetyRuleRead:
        actor = ClinicalSafetyRuleService._require_actor(actor, AUTHOR_ROLES)
        if ClinicalSafetyRuleRepository.get_latest_by_key(db, payload.rule_key):
            raise ClinicalSafetyConflictError(
                f"Rule key '{payload.rule_key}' already exists; supersede it instead."
            )
        content = SafetyRuleContent.model_validate(
            payload.model_dump(exclude={"rule_key"})
        )
        knowledge_facts = ClinicalSafetyRuleService._active_knowledge_facts(
            db,
            content.knowledge_fact_ids,
            as_of=date.today(),
        )
        digest = safety_rule_content_digest(
            rule_key=payload.rule_key,
            version=1,
            content=content,
            knowledge_facts=knowledge_facts,
        )
        try:
            rule = ClinicalSafetyRuleRepository.create(
                db,
                rule_key=payload.rule_key,
                version=1,
                content=content,
                content_sha256=digest,
                knowledge_facts=knowledge_facts,
                created_by_user_id=actor.id,
            )
            AuditLogRepository.create(
                db,
                entity_type="clinical_safety_rule",
                entity_id=rule.id,
                event_type="clinical_safety_rule_created",
                to_state="draft",
                event_data={
                    "rule_key": rule.rule_key,
                    "version": rule.version,
                    "content_sha256": digest,
                    "knowledge_fact_count": len(knowledge_facts),
                },
                commit=False,
                **actor_data(actor),
            )
            ClinicalSafetyRuleService._commit(db)
        except Exception:
            db.rollback()
            raise
        return ClinicalSafetyRuleService._to_read(
            db,
            ClinicalSafetyRuleService._reload(db, rule.id),
        )

    @staticmethod
    def list(
        db: Session,
        **filters,
    ) -> list[SafetyRuleRead]:
        return [
            ClinicalSafetyRuleService._to_read(db, rule)
            for rule in ClinicalSafetyRuleRepository.list(db, **filters)
        ]

    @staticmethod
    def list_active(db: Session, *, as_of: date) -> list[SafetyRuleRead]:
        rules = ClinicalSafetyRuleRepository.list_active(
            db,
            as_of=as_of,
            for_share=True,
        )
        result: list[SafetyRuleRead] = []
        for rule in rules:
            ClinicalSafetyRuleService._verify(db, rule)
            ClinicalSafetyRuleService._active_knowledge_facts(
                db,
                [link.medical_knowledge_fact_id for link in rule.knowledge_links],
                as_of=as_of,
                unavailable_error=True,
                for_share=True,
            )
            result.append(SafetyRuleRead.model_validate(rule))
        return result

    @staticmethod
    def get(db: Session, rule_id: str) -> SafetyRuleRead:
        return ClinicalSafetyRuleService._to_read(
            db,
            ClinicalSafetyRuleService._reload(db, rule_id),
        )

    @staticmethod
    def update(
        db: Session,
        rule_id: str,
        payload: SafetyRuleUpdate,
        *,
        actor: User | None,
    ) -> SafetyRuleRead:
        actor = ClinicalSafetyRuleService._require_actor(actor, AUTHOR_ROLES)
        rule = ClinicalSafetyRuleRepository.get_by_id(
            db,
            rule_id,
            for_update=True,
        )
        if rule is None:
            raise ClinicalSafetyNotFoundError(
                f"Clinical safety rule '{rule_id}' was not found."
            )
        ClinicalSafetyRuleService._verify(db, rule)
        if rule.status not in {"draft", "rejected"}:
            raise ClinicalSafetyConflictError(
                "Only draft or rejected safety rules can be edited."
            )
        content = SafetyRuleContent.model_validate(payload)
        knowledge_facts = ClinicalSafetyRuleService._active_knowledge_facts(
            db,
            content.knowledge_fact_ids,
            as_of=date.today(),
        )
        previous_status = rule.status
        previous_hash = rule.content_sha256
        for field in (
            "title",
            "description",
            "clinical_domain",
            "severity",
            "action",
            "message",
            "valid_from",
            "valid_to",
        ):
            setattr(rule, field, getattr(content, field))
        rule.predicate = content.predicate.model_dump(mode="json")
        ClinicalSafetyRuleRepository.replace_knowledge_links(
            db,
            rule,
            knowledge_facts,
        )
        rule.content_sha256 = safety_rule_content_digest(
            rule_key=rule.rule_key,
            version=rule.version,
            content=content,
            knowledge_facts=knowledge_facts,
        )
        if previous_status == "rejected":
            rule.status = "draft"
            rule.submitted_at = None
            rule.reviewed_by_user_id = None
            rule.reviewed_at = None
            rule.review_comment = None
        AuditLogRepository.create(
            db,
            entity_type="clinical_safety_rule",
            entity_id=rule.id,
            event_type="clinical_safety_rule_updated",
            from_state=previous_status,
            to_state=rule.status,
            event_data={
                "previous_content_sha256": previous_hash,
                "content_sha256": rule.content_sha256,
                "knowledge_fact_count": len(knowledge_facts),
            },
            commit=False,
            **actor_data(actor),
        )
        ClinicalSafetyRuleService._commit(db)
        return ClinicalSafetyRuleService._to_read(
            db,
            ClinicalSafetyRuleService._reload(db, rule.id),
        )

    @staticmethod
    def submit(
        db: Session,
        rule_id: str,
        *,
        actor: User | None,
    ) -> SafetyRuleRead:
        actor = ClinicalSafetyRuleService._require_actor(actor, AUTHOR_ROLES)
        rule = ClinicalSafetyRuleRepository.get_by_id(db, rule_id, for_update=True)
        if rule is None:
            raise ClinicalSafetyNotFoundError(
                f"Clinical safety rule '{rule_id}' was not found."
            )
        ClinicalSafetyRuleService._verify(db, rule)
        if rule.status not in {"draft", "rejected"}:
            raise ClinicalSafetyConflictError(
                "Only a draft or rejected safety rule can be submitted."
            )
        ClinicalSafetyRuleService._active_knowledge_facts(
            db,
            [link.medical_knowledge_fact_id for link in rule.knowledge_links],
            as_of=date.today(),
        )
        previous_status = rule.status
        rule.status = "in_review"
        rule.submitted_at = datetime.now(timezone.utc)
        rule.reviewed_by_user_id = None
        rule.reviewed_at = None
        rule.review_comment = None
        AuditLogRepository.create(
            db,
            entity_type="clinical_safety_rule",
            entity_id=rule.id,
            event_type="clinical_safety_rule_submitted",
            from_state=previous_status,
            to_state="in_review",
            event_data={"content_sha256": rule.content_sha256},
            commit=False,
            **actor_data(actor),
        )
        ClinicalSafetyRuleService._commit(db)
        return ClinicalSafetyRuleService._to_read(
            db,
            ClinicalSafetyRuleService._reload(db, rule.id),
        )

    @staticmethod
    def review(
        db: Session,
        rule_id: str,
        payload: SafetyRuleReview,
        *,
        actor: User | None,
    ) -> SafetyRuleRead:
        actor = ClinicalSafetyRuleService._require_actor(actor, REVIEW_ROLES)
        rule = ClinicalSafetyRuleRepository.get_by_id(db, rule_id, for_update=True)
        if rule is None:
            raise ClinicalSafetyNotFoundError(
                f"Clinical safety rule '{rule_id}' was not found."
            )
        ClinicalSafetyRuleService._verify(db, rule)
        if rule.status != "in_review":
            raise ClinicalSafetyConflictError("Only an in-review rule can be reviewed.")
        if ClinicalSafetyRuleService._actor_authored_content(db, rule, actor):
            raise ClinicalSafetyAuthorizationError(
                "A safety rule needs review by a different admin or physician."
            )
        if payload.decision == "approved":
            ClinicalSafetyRuleService._active_knowledge_facts(
                db,
                [link.medical_knowledge_fact_id for link in rule.knowledge_links],
                as_of=date.today(),
            )
        now = datetime.now(timezone.utc)
        if payload.decision == "approved" and rule.supersedes_rule_id:
            previous = ClinicalSafetyRuleRepository.get_by_id(
                db,
                rule.supersedes_rule_id,
                for_update=True,
            )
            if previous is None or previous.status != "approved":
                raise ClinicalSafetyConflictError(
                    "The superseded rule is no longer the approved predecessor."
                )
            ClinicalSafetyRuleService._verify(db, previous)
            previous.status = "retired"
            AuditLogRepository.create(
                db,
                entity_type="clinical_safety_rule",
                entity_id=previous.id,
                event_type="clinical_safety_rule_superseded",
                from_state="approved",
                to_state="retired",
                event_data={"replacement_rule_id": rule.id},
                commit=False,
                **actor_data(actor),
            )
        rule.status = payload.decision
        rule.reviewed_by_user_id = actor.id
        rule.reviewed_at = now
        rule.review_comment = payload.comment
        AuditLogRepository.create(
            db,
            entity_type="clinical_safety_rule",
            entity_id=rule.id,
            event_type=f"clinical_safety_rule_{payload.decision}",
            from_state="in_review",
            to_state=payload.decision,
            event_data={"content_sha256": rule.content_sha256},
            commit=False,
            **actor_data(actor),
        )
        ClinicalSafetyRuleService._commit(db)
        return ClinicalSafetyRuleService._to_read(
            db,
            ClinicalSafetyRuleService._reload(db, rule.id),
        )

    @staticmethod
    def supersede(
        db: Session,
        rule_id: str,
        payload: SafetyRuleSupersede,
        *,
        actor: User | None,
    ) -> SafetyRuleRead:
        actor = ClinicalSafetyRuleService._require_actor(actor, AUTHOR_ROLES)
        previous = ClinicalSafetyRuleRepository.get_by_id(
            db,
            rule_id,
            for_update=True,
        )
        if previous is None:
            raise ClinicalSafetyNotFoundError(
                f"Clinical safety rule '{rule_id}' was not found."
            )
        ClinicalSafetyRuleService._verify(db, previous)
        if previous.status != "approved":
            raise ClinicalSafetyConflictError(
                "Only an approved safety rule can be superseded."
            )
        latest = ClinicalSafetyRuleRepository.get_latest_by_key(
            db,
            previous.rule_key,
            for_update=True,
        )
        if latest is None or latest.id != previous.id:
            raise ClinicalSafetyConflictError(
                "Only the latest safety rule version can be superseded."
            )
        if ClinicalSafetyRuleRepository.get_successor(db, previous.id):
            raise ClinicalSafetyConflictError(
                "This safety rule already has a successor."
            )
        content = SafetyRuleContent.model_validate(payload)
        knowledge_facts = ClinicalSafetyRuleService._active_knowledge_facts(
            db,
            content.knowledge_fact_ids,
            as_of=date.today(),
        )
        version = previous.version + 1
        digest = safety_rule_content_digest(
            rule_key=previous.rule_key,
            version=version,
            content=content,
            knowledge_facts=knowledge_facts,
        )
        replacement = ClinicalSafetyRuleRepository.create(
            db,
            rule_key=previous.rule_key,
            version=version,
            content=content,
            content_sha256=digest,
            knowledge_facts=knowledge_facts,
            created_by_user_id=actor.id,
            supersedes_rule_id=previous.id,
        )
        AuditLogRepository.create(
            db,
            entity_type="clinical_safety_rule",
            entity_id=replacement.id,
            event_type="clinical_safety_rule_version_created",
            to_state="draft",
            event_data={
                "rule_key": replacement.rule_key,
                "version": replacement.version,
                "supersedes_rule_id": previous.id,
                "content_sha256": digest,
            },
            commit=False,
            **actor_data(actor),
        )
        ClinicalSafetyRuleService._commit(db)
        return ClinicalSafetyRuleService._to_read(
            db,
            ClinicalSafetyRuleService._reload(db, replacement.id),
        )

    @staticmethod
    def retire(
        db: Session,
        rule_id: str,
        *,
        actor: User | None,
    ) -> SafetyRuleRead:
        actor = ClinicalSafetyRuleService._require_actor(actor, REVIEW_ROLES)
        rule = ClinicalSafetyRuleRepository.get_by_id(db, rule_id, for_update=True)
        if rule is None:
            raise ClinicalSafetyNotFoundError(
                f"Clinical safety rule '{rule_id}' was not found."
            )
        ClinicalSafetyRuleService._verify(db, rule)
        if rule.status != "approved":
            raise ClinicalSafetyConflictError(
                "Only an approved safety rule can be retired."
            )
        if ClinicalSafetyRuleService._actor_authored_content(db, rule, actor):
            raise ClinicalSafetyAuthorizationError(
                "Retirement requires a different admin or physician."
            )
        rule.status = "retired"
        AuditLogRepository.create(
            db,
            entity_type="clinical_safety_rule",
            entity_id=rule.id,
            event_type="clinical_safety_rule_retired",
            from_state="approved",
            to_state="retired",
            event_data={"content_sha256": rule.content_sha256},
            commit=False,
            **actor_data(actor),
        )
        ClinicalSafetyRuleService._commit(db)
        return ClinicalSafetyRuleService._to_read(
            db,
            ClinicalSafetyRuleService._reload(db, rule.id),
        )

    @staticmethod
    def list_audit_logs(db: Session, rule_id: str) -> list[AuditLog]:
        ClinicalSafetyRuleService._reload(db, rule_id)
        return AuditLogRepository.list_by_entity(
            db,
            entity_type="clinical_safety_rule",
            entity_id=rule_id,
        )


class ClinicalSafetyEvaluationService:
    @staticmethod
    def _require_actor(actor: User | None) -> User:
        return ClinicalSafetyRuleService._require_actor(actor, EVALUATE_ROLES)

    @staticmethod
    def _normalize(value: str, *, case_sensitive: bool) -> str:
        return value if case_sensitive else value.casefold()

    @staticmethod
    def _compare(value, condition: SafetyCondition) -> bool:
        operator = condition.operator
        if operator == "is_missing":
            return value is None
        if operator == "is_present":
            return value is not None
        if operator == "is_empty":
            return value is None or value == "" or value == []
        if operator == "is_not_empty":
            return value is not None and value != "" and value != []
        expected = condition.value
        if operator in {"gt", "gte", "lt", "lte", "between"} or (
            operator in {"eq", "ne"}
            and isinstance(value, (int, Decimal))
            and not isinstance(value, bool)
        ):
            actual_number = Decimal(str(value))
            if operator == "between":
                bounds = expected
                lower = Decimal(str(bounds[0]))
                upper = Decimal(str(bounds[1]))
                return lower <= actual_number <= upper
            expected_number = Decimal(str(expected))
            return {
                "eq": actual_number == expected_number,
                "ne": actual_number != expected_number,
                "gt": actual_number > expected_number,
                "gte": actual_number >= expected_number,
                "lt": actual_number < expected_number,
                "lte": actual_number <= expected_number,
            }[operator]
        if isinstance(value, bool):
            return value == expected if operator == "eq" else value != expected
        if isinstance(value, list):
            actual_values = [
                ClinicalSafetyEvaluationService._normalize(
                    str(item),
                    case_sensitive=condition.case_sensitive,
                )
                for item in value
            ]
            if operator == "contains_text":
                needle = ClinicalSafetyEvaluationService._normalize(
                    str(expected),
                    case_sensitive=condition.case_sensitive,
                )
                return any(needle in item for item in actual_values)
            if operator == "contains_any":
                needles = [
                    ClinicalSafetyEvaluationService._normalize(
                        str(item),
                        case_sensitive=condition.case_sensitive,
                    )
                    for item in expected
                ]
                return any(
                    needle in actual
                    for needle in needles
                    for actual in actual_values
                )
        actual_text = ClinicalSafetyEvaluationService._normalize(
            str(value),
            case_sensitive=condition.case_sensitive,
        )
        if operator == "contains_text":
            expected_text = ClinicalSafetyEvaluationService._normalize(
                str(expected),
                case_sensitive=condition.case_sensitive,
            )
            return expected_text in actual_text
        if operator == "in":
            expected_values = {
                ClinicalSafetyEvaluationService._normalize(
                    str(item),
                    case_sensitive=condition.case_sensitive,
                )
                for item in expected
            }
            return actual_text in expected_values
        expected_text = ClinicalSafetyEvaluationService._normalize(
            str(expected),
            case_sensitive=condition.case_sensitive,
        )
        return (
            actual_text == expected_text
            if operator == "eq"
            else actual_text != expected_text
        )

    @staticmethod
    def _observation_candidates(
        context: ClinicalContextRead,
        condition: SafetyCondition,
    ) -> list:
        candidates = []
        for report in context.reports:
            for observation in report.observations:
                if (
                    observation.code_system != condition.code_system
                    or observation.code != condition.code
                ):
                    continue
                if (
                    condition.code_system_uri is not None
                    and observation.code_system_uri != condition.code_system_uri
                ):
                    continue
                if (
                    condition.code_system_version is not None
                    and observation.code_system_version
                    != condition.code_system_version
                ):
                    continue
                if (
                    condition.unit_code is not None
                    and observation.unit_code != condition.unit_code
                ):
                    continue
                candidates.append(observation)
        return candidates

    @staticmethod
    def _evaluate_condition(
        context: ClinicalContextRead,
        condition: SafetyCondition,
        condition_index: int,
    ) -> SafetyConditionTrace:
        matched_record_ids: list[str] = []
        if condition.source == "intake":
            value = (
                getattr(context.intake, condition.field)
                if context.intake is not None
                else None
            )
            matched = ClinicalSafetyEvaluationService._compare(value, condition)
            if matched and context.intake is not None:
                matched_record_ids.append(context.intake.id)
        else:
            candidates = ClinicalSafetyEvaluationService._observation_candidates(
                context,
                condition,
            )
            if condition.field == "existence":
                matched = bool(candidates)
                if condition.operator == "is_missing":
                    matched = not matched
                if matched and condition.operator == "is_present":
                    matched_record_ids = [item.id for item in candidates]
            elif condition.operator == "is_missing":
                matched = not candidates or all(
                    getattr(item, condition.field) is None for item in candidates
                )
            elif condition.operator == "is_present":
                matched_items = [
                    item
                    for item in candidates
                    if getattr(item, condition.field) is not None
                ]
                matched = bool(matched_items)
                matched_record_ids = [item.id for item in matched_items]
            else:
                matched_items = [
                    item
                    for item in candidates
                    if getattr(item, condition.field) is not None
                    and ClinicalSafetyEvaluationService._compare(
                        getattr(item, condition.field),
                        condition,
                    )
                ]
                matched = bool(matched_items)
                matched_record_ids = [item.id for item in matched_items]
        return SafetyConditionTrace(
            condition_index=condition_index,
            matched=matched,
            source=condition.source,
            field=condition.field,
            operator=condition.operator,
            code_system=condition.code_system,
            code=condition.code,
            matched_record_ids=matched_record_ids,
        )

    @staticmethod
    def _evaluate_rule(
        context: ClinicalContextRead,
        rule: ClinicalSafetyRule,
    ) -> tuple[bool, list[dict]]:
        predicate = SafetyRuleContent.model_validate(
            ClinicalSafetyRuleService._content_from_rule(rule)
        ).predicate
        traces = [
            ClinicalSafetyEvaluationService._evaluate_condition(
                context,
                condition,
                index,
            )
            for index, condition in enumerate(predicate.conditions, start=1)
        ]
        values = [trace.matched for trace in traces]
        matched = all(values) if predicate.combinator == "all" else any(values)
        return matched, [trace.model_dump(mode="json") for trace in traces]

    @staticmethod
    def _active_rules(db: Session, *, as_of: date) -> list[ClinicalSafetyRule]:
        rules = ClinicalSafetyRuleRepository.list_active(db, as_of=as_of)
        for rule in rules:
            ClinicalSafetyRuleService._verify(db, rule)
            active = ClinicalSafetyRuleService._active_knowledge_facts(
                db,
                [link.medical_knowledge_fact_id for link in rule.knowledge_links],
                as_of=as_of,
                unavailable_error=True,
            )
            if active != ClinicalSafetyRuleService._knowledge_snapshot(rule):
                raise ClinicalSafetyIntegrityError(
                    "An active safety rule evidence snapshot no longer matches."
                )
        return rules

    @staticmethod
    @clinical_record_write
    def evaluate(
        db: Session,
        visit_id: str,
        payload: SafetyEvaluationRequest,
        *,
        actor: User | None,
    ) -> SafetyEvaluationRead:
        actor = ClinicalSafetyEvaluationService._require_actor(actor)
        if VisitRepository.get_by_id(db, visit_id) is None:
            raise ClinicalSafetyNotFoundError(f"Visit '{visit_id}' was not found.")
        context = ClinicalContextService.get_current_context(db, visit_id)
        context_hash = clinical_context_digest(context)
        if (
            payload.expected_clinical_context_sha256 is not None
            and payload.expected_clinical_context_sha256 != context_hash
        ):
            raise ClinicalSafetyConflictError(
                "The clinical context changed; reload it before evaluating safety."
            )
        rules = ClinicalSafetyEvaluationService._active_rules(
            db,
            as_of=date.today(),
        )
        rule_set_hash = safety_rule_set_digest(rules)
        if (
            payload.expected_rule_set_sha256 is not None
            and payload.expected_rule_set_sha256 != rule_set_hash
        ):
            raise ClinicalSafetyConflictError(
                "The approved safety rule set changed; reload before evaluating."
            )
        findings: list[dict] = []
        for rule in rules:
            matched, trace = ClinicalSafetyEvaluationService._evaluate_rule(
                context,
                rule,
            )
            if not matched:
                continue
            findings.append(
                {
                    "rule_id": rule.id,
                    "rule_key": rule.rule_key,
                    "rule_version": rule.version,
                    "rule_content_sha256": rule.content_sha256,
                    "title": rule.title,
                    "severity": rule.severity,
                    "action": rule.action,
                    "message": rule.message,
                    "knowledge_fact_ids": [
                        link.medical_knowledge_fact_id
                        for link in rule.knowledge_links
                    ],
                    "condition_trace": trace,
                }
            )
        highest_severity = (
            max(
                (finding["severity"] for finding in findings),
                key=SEVERITY_ORDER.__getitem__,
            )
            if findings
            else None
        )
        outcome = (
            "no_active_rules"
            if not rules
            else "alerts_present"
            if findings
            else "no_alerts"
        )
        evaluation_id = str(uuid.uuid4())
        report_ids = [report.id for report in context.reports]
        intake_id = context.intake.id if context.intake is not None else None
        result_hash = safety_result_digest(
            evaluation_id=evaluation_id,
            visit_id=visit_id,
            intake_id=intake_id,
            report_ids=report_ids,
            outcome=outcome,
            evaluated_rule_count=len(rules),
            triggered_count=len(findings),
            highest_severity=highest_severity,
            clinical_context_sha256=context_hash,
            rule_set_sha256=rule_set_hash,
            evaluated_by_user_id=actor.id,
            findings=findings,
        )
        evaluation = ClinicalSafetyEvaluationRepository.create(
            db,
            evaluation_id=evaluation_id,
            visit_id=visit_id,
            intake_id=intake_id,
            report_ids=report_ids,
            engine_version=ENGINE_VERSION,
            outcome=outcome,
            evaluated_rule_count=len(rules),
            triggered_count=len(findings),
            highest_severity=highest_severity,
            clinical_context_sha256=context_hash,
            rule_set_sha256=rule_set_hash,
            result_sha256=result_hash,
            evaluated_by_user_id=actor.id,
            findings=findings,
        )
        AuditLogRepository.create(
            db,
            entity_type="clinical_safety_evaluation",
            entity_id=evaluation.id,
            event_type="clinical_safety_evaluation_completed",
            to_state=outcome,
            event_data={
                "visit_id": visit_id,
                "evaluated_rule_count": len(rules),
                "triggered_count": len(findings),
                "highest_severity": highest_severity,
                "clinical_context_sha256": context_hash,
                "rule_set_sha256": rule_set_hash,
                "result_sha256": result_hash,
            },
            commit=False,
            **actor_data(actor),
        )
        return ClinicalSafetyEvaluationService._to_read(evaluation)

    @staticmethod
    def _finding_payload(evaluation: ClinicalSafetyEvaluation) -> list[dict]:
        return [
            {
                "rule_id": finding.rule_id,
                "rule_key": finding.rule_key,
                "rule_version": finding.rule_version,
                "rule_content_sha256": finding.rule_content_sha256,
                "title": finding.title,
                "severity": finding.severity,
                "action": finding.action,
                "message": finding.message,
                "knowledge_fact_ids": list(finding.knowledge_fact_ids),
                "condition_trace": list(finding.condition_trace),
            }
            for finding in evaluation.findings
        ]

    @staticmethod
    def _verify(evaluation: ClinicalSafetyEvaluation) -> None:
        findings = ClinicalSafetyEvaluationService._finding_payload(evaluation)
        if evaluation.triggered_count != len(findings):
            raise ClinicalSafetyIntegrityError(
                "Stored clinical safety evaluation has an invalid finding count."
            )
        expected = safety_result_digest(
            evaluation_id=evaluation.id,
            visit_id=evaluation.visit_id,
            intake_id=evaluation.intake_id,
            report_ids=list(evaluation.report_ids),
            outcome=evaluation.outcome,
            evaluated_rule_count=evaluation.evaluated_rule_count,
            triggered_count=evaluation.triggered_count,
            highest_severity=evaluation.highest_severity,
            clinical_context_sha256=evaluation.clinical_context_sha256,
            rule_set_sha256=evaluation.rule_set_sha256,
            evaluated_by_user_id=evaluation.evaluated_by_user_id,
            findings=findings,
        )
        if expected != evaluation.result_sha256:
            raise ClinicalSafetyIntegrityError(
                "Stored clinical safety evaluation failed its integrity check."
            )

    @staticmethod
    def _to_read(evaluation: ClinicalSafetyEvaluation) -> SafetyEvaluationRead:
        ClinicalSafetyEvaluationService._verify(evaluation)
        return SafetyEvaluationRead.model_validate(evaluation)

    @staticmethod
    def _reload(
        db: Session,
        evaluation_id: str,
    ) -> ClinicalSafetyEvaluation:
        evaluation = ClinicalSafetyEvaluationRepository.get_by_id(
            db,
            evaluation_id,
        )
        if evaluation is None:
            raise ClinicalSafetyNotFoundError(
                f"Clinical safety evaluation '{evaluation_id}' was not found."
            )
        return evaluation

    @staticmethod
    def get(db: Session, evaluation_id: str) -> SafetyEvaluationRead:
        return ClinicalSafetyEvaluationService._to_read(
            ClinicalSafetyEvaluationService._reload(db, evaluation_id)
        )

    @staticmethod
    def list_by_visit(
        db: Session,
        visit_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[SafetyEvaluationRead]:
        if VisitRepository.get_by_id(db, visit_id) is None:
            raise ClinicalSafetyNotFoundError(f"Visit '{visit_id}' was not found.")
        return [
            ClinicalSafetyEvaluationService._to_read(item)
            for item in ClinicalSafetyEvaluationRepository.list_by_visit(
                db,
                visit_id,
                skip=skip,
                limit=limit,
            )
        ]

    @staticmethod
    def get_latest_by_visit(
        db: Session,
        visit_id: str,
    ) -> SafetyEvaluationRead:
        if VisitRepository.get_by_id(db, visit_id) is None:
            raise ClinicalSafetyNotFoundError(f"Visit '{visit_id}' was not found.")
        evaluation = ClinicalSafetyEvaluationRepository.get_latest_by_visit(
            db,
            visit_id,
        )
        if evaluation is None:
            raise ClinicalSafetyNotFoundError(
                f"Visit '{visit_id}' has no safety evaluation."
            )
        return ClinicalSafetyEvaluationService._to_read(evaluation)

    @staticmethod
    def list_audit_logs(db: Session, evaluation_id: str) -> list[AuditLog]:
        ClinicalSafetyEvaluationService._reload(db, evaluation_id)
        return AuditLogRepository.list_by_entity(
            db,
            entity_type="clinical_safety_evaluation",
            entity_id=evaluation_id,
        )
