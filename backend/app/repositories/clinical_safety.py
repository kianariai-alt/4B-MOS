from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models.clinical_safety import (
    ClinicalSafetyEvaluation,
    ClinicalSafetyFinding,
    ClinicalSafetyRule,
    ClinicalSafetyRuleKnowledge,
)
from backend.app.schemas.clinical_safety import SafetyRuleContent


class ClinicalSafetyRuleRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        rule_id: str,
        *,
        for_update: bool = False,
    ) -> ClinicalSafetyRule | None:
        statement = (
            select(ClinicalSafetyRule)
            .options(selectinload(ClinicalSafetyRule.knowledge_links))
            .where(ClinicalSafetyRule.id == rule_id)
        )
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    @staticmethod
    def get_latest_by_key(
        db: Session,
        rule_key: str,
        *,
        for_update: bool = False,
    ) -> ClinicalSafetyRule | None:
        statement = (
            select(ClinicalSafetyRule)
            .options(selectinload(ClinicalSafetyRule.knowledge_links))
            .where(ClinicalSafetyRule.rule_key == rule_key)
            .order_by(ClinicalSafetyRule.version.desc())
            .limit(1)
        )
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    @staticmethod
    def get_successor(
        db: Session,
        rule_id: str,
    ) -> ClinicalSafetyRule | None:
        return db.scalar(
            select(ClinicalSafetyRule)
            .options(selectinload(ClinicalSafetyRule.knowledge_links))
            .where(ClinicalSafetyRule.supersedes_rule_id == rule_id)
        )

    @staticmethod
    def list(
        db: Session,
        *,
        status: str | None = None,
        clinical_domain: str | None = None,
        severity: str | None = None,
        rule_key: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ClinicalSafetyRule]:
        statement = (
            select(ClinicalSafetyRule)
            .options(selectinload(ClinicalSafetyRule.knowledge_links))
            .order_by(
                ClinicalSafetyRule.rule_key.asc(),
                ClinicalSafetyRule.version.desc(),
            )
            .offset(skip)
            .limit(limit)
        )
        if status is not None:
            statement = statement.where(ClinicalSafetyRule.status == status)
        if clinical_domain is not None:
            statement = statement.where(
                func.lower(ClinicalSafetyRule.clinical_domain)
                == clinical_domain.casefold()
            )
        if severity is not None:
            statement = statement.where(ClinicalSafetyRule.severity == severity)
        if rule_key is not None:
            statement = statement.where(ClinicalSafetyRule.rule_key == rule_key)
        if search is not None:
            pattern = f"%{search.casefold()}%"
            statement = statement.where(
                or_(
                    func.lower(ClinicalSafetyRule.title).like(pattern),
                    func.lower(ClinicalSafetyRule.description).like(pattern),
                    func.lower(ClinicalSafetyRule.rule_key).like(pattern),
                )
            )
        return list(db.scalars(statement).all())

    @staticmethod
    def list_active(
        db: Session,
        *,
        as_of: date,
        for_share: bool = False,
    ) -> list[ClinicalSafetyRule]:
        statement = (
            select(ClinicalSafetyRule)
            .options(selectinload(ClinicalSafetyRule.knowledge_links))
            .where(
                ClinicalSafetyRule.status == "approved",
                or_(
                    ClinicalSafetyRule.valid_from.is_(None),
                    ClinicalSafetyRule.valid_from <= as_of,
                ),
                or_(
                    ClinicalSafetyRule.valid_to.is_(None),
                    ClinicalSafetyRule.valid_to >= as_of,
                ),
            )
            .order_by(
                ClinicalSafetyRule.rule_key.asc(),
                ClinicalSafetyRule.version.asc(),
            )
        )
        if for_share:
            statement = statement.with_for_update(read=True)
        return list(db.scalars(statement).all())

    @staticmethod
    def create(
        db: Session,
        *,
        rule_key: str,
        version: int,
        content: SafetyRuleContent,
        content_sha256: str,
        knowledge_facts: list[tuple[str, str]],
        created_by_user_id: str,
        supersedes_rule_id: str | None = None,
    ) -> ClinicalSafetyRule:
        rule = ClinicalSafetyRule(
            rule_key=rule_key,
            version=version,
            title=content.title,
            description=content.description,
            clinical_domain=content.clinical_domain,
            severity=content.severity,
            action=content.action,
            message=content.message,
            predicate=content.predicate.model_dump(mode="json"),
            valid_from=content.valid_from,
            valid_to=content.valid_to,
            content_sha256=content_sha256,
            created_by_user_id=created_by_user_id,
            supersedes_rule_id=supersedes_rule_id,
        )
        rule.knowledge_links = ClinicalSafetyRuleRepository._build_links(
            knowledge_facts
        )
        db.add(rule)
        db.flush()
        return rule

    @staticmethod
    def replace_knowledge_links(
        db: Session,
        rule: ClinicalSafetyRule,
        knowledge_facts: list[tuple[str, str]],
    ) -> None:
        rule.knowledge_links.clear()
        db.flush()
        rule.knowledge_links.extend(
            ClinicalSafetyRuleRepository._build_links(knowledge_facts)
        )
        db.flush()

    @staticmethod
    def _build_links(
        knowledge_facts: list[tuple[str, str]],
    ) -> list[ClinicalSafetyRuleKnowledge]:
        return [
            ClinicalSafetyRuleKnowledge(
                sort_order=index,
                medical_knowledge_fact_id=fact_id,
                fact_content_sha256=content_sha256,
            )
            for index, (fact_id, content_sha256) in enumerate(
                knowledge_facts,
                start=1,
            )
        ]


class ClinicalSafetyEvaluationRepository:
    @staticmethod
    def get_by_id(
        db: Session,
        evaluation_id: str,
    ) -> ClinicalSafetyEvaluation | None:
        return db.scalar(
            select(ClinicalSafetyEvaluation)
            .options(selectinload(ClinicalSafetyEvaluation.findings))
            .where(ClinicalSafetyEvaluation.id == evaluation_id)
        )

    @staticmethod
    def list_by_visit(
        db: Session,
        visit_id: str,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[ClinicalSafetyEvaluation]:
        return list(
            db.scalars(
                select(ClinicalSafetyEvaluation)
                .options(selectinload(ClinicalSafetyEvaluation.findings))
                .where(ClinicalSafetyEvaluation.visit_id == visit_id)
                .order_by(
                    ClinicalSafetyEvaluation.created_at.desc(),
                    ClinicalSafetyEvaluation.id.desc(),
                )
                .offset(skip)
                .limit(limit)
            ).all()
        )

    @staticmethod
    def get_latest_by_visit(
        db: Session,
        visit_id: str,
    ) -> ClinicalSafetyEvaluation | None:
        return db.scalar(
            select(ClinicalSafetyEvaluation)
            .options(selectinload(ClinicalSafetyEvaluation.findings))
            .where(ClinicalSafetyEvaluation.visit_id == visit_id)
            .order_by(
                ClinicalSafetyEvaluation.created_at.desc(),
                ClinicalSafetyEvaluation.id.desc(),
            )
            .limit(1)
        )

    @staticmethod
    def create(
        db: Session,
        *,
        evaluation_id: str,
        visit_id: str,
        intake_id: str | None,
        report_ids: list[str],
        engine_version: str,
        outcome: str,
        evaluated_rule_count: int,
        triggered_count: int,
        highest_severity: str | None,
        clinical_context_sha256: str,
        rule_set_sha256: str,
        result_sha256: str,
        evaluated_by_user_id: str,
        findings: list[dict],
    ) -> ClinicalSafetyEvaluation:
        evaluation = ClinicalSafetyEvaluation(
            id=evaluation_id,
            visit_id=visit_id,
            intake_id=intake_id,
            report_ids=list(report_ids),
            engine_version=engine_version,
            outcome=outcome,
            evaluated_rule_count=evaluated_rule_count,
            triggered_count=triggered_count,
            highest_severity=highest_severity,
            clinical_context_sha256=clinical_context_sha256,
            rule_set_sha256=rule_set_sha256,
            result_sha256=result_sha256,
            evaluated_by_user_id=evaluated_by_user_id,
        )
        evaluation.findings = [
            ClinicalSafetyFinding(sort_order=index, **finding)
            for index, finding in enumerate(findings, start=1)
        ]
        db.add(evaluation)
        db.flush()
        return evaluation
