"""Read-only controlled-pilot readiness gate.

This service verifies technical and governance prerequisites that the system can
actually prove. It deliberately does not authorize clinical use or mark manual
external acceptance gates as complete.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.readiness import database_readiness_issues
from backend.app.models.user import User
from backend.app.repositories.protocol import ProtocolRepository
from backend.app.schemas.pilot_readiness import (
    ControlledPilotReadinessRead,
    PilotManualGateRead,
    PilotReadinessCheckRead,
)
from backend.app.services.clinical_learning_review import (
    ClinicalLearningIntegrityError,
    ClinicalLearningReviewService,
)
from backend.app.services.clinical_safety import (
    ClinicalSafetyEvaluationService,
    ClinicalSafetyIntegrityError,
    ClinicalSafetyRuleUnavailableError,
)
from backend.app.services.session_finalization import evidence_digest
from backend.app.services.protocol_governance import (
    ProtocolGovernanceIntegrityError,
    ProtocolGovernanceNotFoundError,
    ProtocolGovernanceService,
)


MANUAL_GATES = (
    ("clinical_protocol_signoff", "clinical_protocol_content_signoff_required"),
    ("clinical_safety_signoff", "clinical_safety_rule_content_signoff_required"),
    ("backup_restore", "backup_restore_rehearsal_required"),
    ("security_perimeter", "security_perimeter_review_required"),
    ("monitoring_alerting", "monitoring_alerting_validation_required"),
    ("human_ui_acceptance", "human_ui_acceptance_required"),
    ("privacy_retention_legal", "privacy_retention_legal_review_required"),
)


def _check(
    name: str,
    *,
    passed: bool,
    pass_code: str,
    fail_code: str,
) -> PilotReadinessCheckRead:
    return PilotReadinessCheckRead(
        name=name,
        status="pass" if passed else "fail",
        code=pass_code if passed else fail_code,
    )


class ControlledPilotReadinessService:
    @staticmethod
    def build(
        db: Session,
        config: Settings,
    ) -> ControlledPilotReadinessRead:
        checks: list[PilotReadinessCheckRead] = []

        runtime_safe = (
            config.ENVIRONMENT == "production"
            and not config.DEBUG
            and not config.BOOTSTRAP_ENABLED
        )
        checks.append(
            _check(
                "runtime_configuration",
                passed=runtime_safe,
                pass_code="production_runtime_safe",
                fail_code="production_runtime_required",
            )
        )

        dialect = db.get_bind().dialect.name
        database_ready = False
        try:
            issues = database_readiness_issues(db)
            database_ready = not issues
            checks.append(
                PilotReadinessCheckRead(
                    name="database_schema",
                    status="pass" if database_ready else "fail",
                    code=(
                        "database_schema_ready"
                        if database_ready
                        else issues[0]
                    ),
                )
            )
        except SQLAlchemyError:
            db.rollback()
            checks.append(
                PilotReadinessCheckRead(
                    name="database_schema",
                    status="fail",
                    code="database_unavailable_or_uninitialized",
                )
            )

        if database_ready:
            checks.append(
                _check(
                    "database_engine",
                    passed=dialect == "postgresql",
                    pass_code="postgresql_concurrency_ready",
                    fail_code="postgresql_required_for_controlled_pilot",
                )
            )
        else:
            checks.append(
                PilotReadinessCheckRead(
                    name="database_engine",
                    status="blocked",
                    code="database_schema_not_ready",
                )
            )

        if database_ready:
            try:
                required_roles = {
                    "admin": 1,
                    "physician": 2,
                    "nurse": 1,
                    "operator": 1,
                }
                role_ok = True
                for role, minimum in required_roles.items():
                    count = db.scalar(
                        select(func.count())
                        .select_from(User)
                        .where(
                            User.role == role,
                            User.is_active.is_(True),
                        )
                    ) or 0
                    if count < minimum:
                        role_ok = False
                        break
                checks.append(
                    _check(
                        "role_separation",
                        passed=role_ok,
                        pass_code="required_staff_roles_present",
                        fail_code="required_staff_roles_missing",
                    )
                )
            except SQLAlchemyError:
                db.rollback()
                checks.append(
                    PilotReadinessCheckRead(
                        name="role_separation",
                        status="fail",
                        code="staff_role_check_failed",
                    )
                )
        else:
            checks.append(
                PilotReadinessCheckRead(
                    name="role_separation",
                    status="blocked",
                    code="database_schema_not_ready",
                )
            )

        if database_ready:
            try:
                protocols = ProtocolRepository.list(db)
                active_protocols = [item for item in protocols if item.is_active]
                if not active_protocols:
                    checks.append(
                        PilotReadinessCheckRead(
                            name="protocol_registry",
                            status="fail",
                            code="active_protocol_missing",
                        )
                    )
                else:
                    seen_codes: set[str] = set()
                    for protocol in protocols:
                        if protocol.code in seen_codes:
                            continue
                        ProtocolGovernanceService.get_lineage(db, protocol.id)
                        seen_codes.add(protocol.code)
                    checks.append(
                        PilotReadinessCheckRead(
                            name="protocol_registry",
                            status="pass",
                            code="protocol_registry_lineage_consistent",
                        )
                    )
            except (
                SQLAlchemyError,
                ProtocolGovernanceIntegrityError,
                ProtocolGovernanceNotFoundError,
            ):
                db.rollback()
                checks.append(
                    PilotReadinessCheckRead(
                        name="protocol_registry",
                        status="fail",
                        code="protocol_registry_integrity_failed",
                    )
                )
        else:
            checks.append(
                PilotReadinessCheckRead(
                    name="protocol_registry",
                    status="blocked",
                    code="database_schema_not_ready",
                )
            )

        if database_ready:
            try:
                active_rules = ClinicalSafetyEvaluationService._active_rules(
                    db,
                    as_of=date.today(),
                )
                checks.append(
                    _check(
                        "clinical_safety_registry",
                        passed=bool(active_rules),
                        pass_code="active_safety_rule_set_verified",
                        fail_code="active_safety_rule_missing",
                    )
                )
            except (
                SQLAlchemyError,
                ClinicalSafetyIntegrityError,
                ClinicalSafetyRuleUnavailableError,
            ):
                db.rollback()
                checks.append(
                    PilotReadinessCheckRead(
                        name="clinical_safety_registry",
                        status="fail",
                        code="clinical_safety_registry_integrity_failed",
                    )
                )
        else:
            checks.append(
                PilotReadinessCheckRead(
                    name="clinical_safety_registry",
                    status="blocked",
                    code="database_schema_not_ready",
                )
            )

        if database_ready:
            try:
                ClinicalLearningReviewService.get_review(db)
                checks.append(
                    PilotReadinessCheckRead(
                        name="clinical_feedback_integrity",
                        status="pass",
                        code="clinical_feedback_provenance_verified",
                    )
                )
            except (SQLAlchemyError, ClinicalLearningIntegrityError):
                db.rollback()
                checks.append(
                    PilotReadinessCheckRead(
                        name="clinical_feedback_integrity",
                        status="fail",
                        code="clinical_feedback_integrity_failed",
                    )
                )
        else:
            checks.append(
                PilotReadinessCheckRead(
                    name="clinical_feedback_integrity",
                    status="blocked",
                    code="database_schema_not_ready",
                )
            )

        if database_ready:
            try:
                ProtocolGovernanceService.list_cases(db)
                ProtocolGovernanceService.list_releases(db)
                ProtocolGovernanceService.list_recoveries(db)
                checks.append(
                    PilotReadinessCheckRead(
                        name="protocol_governance_integrity",
                        status="pass",
                        code="protocol_governance_history_verified",
                    )
                )
            except (SQLAlchemyError, ProtocolGovernanceIntegrityError):
                db.rollback()
                checks.append(
                    PilotReadinessCheckRead(
                        name="protocol_governance_integrity",
                        status="fail",
                        code="protocol_governance_integrity_failed",
                    )
                )
        else:
            checks.append(
                PilotReadinessCheckRead(
                    name="protocol_governance_integrity",
                    status="blocked",
                    code="database_schema_not_ready",
                )
            )

        automated_ready = all(item.status == "pass" for item in checks)
        manual_gates = [
            PilotManualGateRead(
                name=name,
                status="manual_required",
                code=code,
            )
            for name, code in MANUAL_GATES
        ]
        status = (
            "automated_prerequisites_passed"
            if automated_ready
            else "blocked"
        )
        warnings = [
            "automated_gate_does_not_authorize_clinical_use",
            "manual_release_decision_remains_required",
        ]
        digest_payload = {
            "schema_version": 1,
            "status": status,
            "application": config.PROJECT_NAME,
            "version": config.PROJECT_VERSION,
            "database_dialect": dialect,
            "automated_checks": [
                item.model_dump(mode="json") for item in checks
            ],
            "manual_gates": [
                item.model_dump(mode="json") for item in manual_gates
            ],
            "warnings": warnings,
            "controlled_pilot_authorized": False,
            "is_clinical_clearance": False,
            "requires_human_release_decision": True,
        }
        return ControlledPilotReadinessRead(
            status=status,
            generated_at=datetime.now(timezone.utc),
            application=config.PROJECT_NAME,
            version=config.PROJECT_VERSION,
            database_dialect=dialect,
            readiness_sha256=evidence_digest(digest_payload),
            automated_checks=checks,
            manual_gates=manual_gates,
            warnings=warnings,
        )
