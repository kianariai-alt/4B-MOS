"""Optional decision port and explicitly synthetic adapters, never registered in API.

All mocks accept only the exact built-in fixture (including its values and hashes).
They cannot collect arbitrary patient records, even with a synthetic-looking ID.
"""

from datetime import datetime, timedelta, timezone
from typing import Protocol

from pydantic import ValidationError

from backend.app.schemas.clinical_decision_exchange import (
    DecisionModelReference, DecisionModelResult, DecisionSignal, decision_digest,
)
from backend.app.schemas.clinical_integration import (
    ComponentVersion, CoreFinding, CoreInput, CoreOutput, KnowledgeReference, RecordReference, SourceObservation,
)

MAX_DECISION_AGE = timedelta(hours=24)  # Administrative freshness limit, not clinical validation.


class DecisionAdapter(Protocol):
    def current_version(self) -> ComponentVersion:
        """Trusted deployed model identity, independently checked by the caller."""
        ...

    def collect(self, context: CoreInput) -> DecisionModelResult:
        """Bounded read-only I/O; never approves a finding or changes Safety."""
        ...


def collect_decision(
    context: CoreInput, adapter: DecisionAdapter | None, *, now: datetime,
    approved_knowledge: tuple[KnowledgeReference, ...] = (),
) -> DecisionModelReference:
    """Quarantine invalid/stale output; never return exception text or secrets.

    Only exact knowledge references supplied by the server's Registry adapter
    are allowed, and their validity dates are checked again. Applicability is
    not asserted; research outputs never become confirmed findings or choices.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("An aware orchestration timestamp is required.")
    if adapter is None:
        return DecisionModelReference(status="missing", issue_codes=("decision_model_unavailable",))
    component = None
    try:
        component = ComponentVersion.model_validate(adapter.current_version().model_dump(mode="json"))
        if component.kind != "model":
            raise ValueError("Expected model provenance.")
        # Deep-copy prevents producer mutation of source objects from leaking.
        result = DecisionModelResult.model_validate(
            adapter.collect(context.model_copy(deep=True)).model_dump(mode="json"),
        )
        if (result.visit_id != context.visit_id
                or result.clinical_context_sha256 != context.clinical_context_sha256
                or result.component != component
                or result.generated_at > now + timedelta(minutes=5)):
            raise ValueError("Model envelope does not match the invocation.")
        allowed = {decision_digest(item.source) for item in context.observations}
        if any(decision_digest(item) not in allowed for item in result.source_references):
            raise ValueError("Model refers to an unknown source version.")
        allowed_knowledge = {decision_digest(item) for item in approved_knowledge
                             if (not item.valid_from or item.valid_from <= now.date())
                             and (not item.valid_to or item.valid_to >= now.date())}
        if any(decision_digest(item) not in allowed_knowledge for item in result.knowledge):
            raise ValueError("Model knowledge is not bound to current approved Registry references.")
        if result.valid_until <= now or now - result.generated_at > MAX_DECISION_AGE:
            return DecisionModelReference(status="expired", component=component,
                                          issue_codes=("decision_output_expired",))
        return DecisionModelReference(
            status="available", component=component, result=result,
            result_sha256=decision_digest(result), issue_codes=("decision_requires_physician_review",),
        )
    except (ValidationError, ValueError, TypeError, AttributeError):
        return DecisionModelReference(status="invalid", component=component,
                                      issue_codes=("decision_output_invalid",))
    except Exception:
        return DecisionModelReference(status="unavailable", component=component,
                                      issue_codes=("decision_adapter_unavailable",))


def synthetic_core_input() -> CoreInput:
    """Fixed fabricated knee fixture; no patient-identifying fields or URLs."""
    clinical = SourceObservation(
        source=RecordReference(record_type="clinical_intake", record_id="synthetic-knee-intake",
                               version=1, content_sha256="a" * 64, field="exam_findings"),
        observation={"category": "clinical_test", "code_system": "LOCAL",
                     "code": "SYNTHETIC_KNEE_MOVEMENT", "display_name": "Fabricated knee examination",
                     "value_type": "boolean", "boolean_value": True, "body_site": "left knee"},
    )
    imaging = SourceObservation(
        source=RecordReference(record_type="paraclinical_report", record_id="synthetic-knee-mri-report",
                               version=1, content_sha256="b" * 64, field="observation",
                               observation_id="synthetic-mri-effusion"),
        observation={"category": "imaging", "code_system": "LOCAL",
                     "code": "SYNTHETIC_EFFUSION", "display_name": "Fabricated MRI observation",
                     "value_type": "boolean", "boolean_value": True, "body_site": "left knee"},
    )
    return CoreInput(visit_id="synthetic-knee-visit", clinical_context_sha256="c" * 64,
                     observations=(clinical, imaging))


def _synthetic_guard(context: CoreInput, core: str | None = None) -> None:
    fixture = synthetic_core_input()
    allowed = {decision_digest(fixture)}
    if core is not None:
        fixture = fixture.model_copy(update={"observations": tuple(
            item for item in fixture.observations
            if (item.observation.category == "imaging") == (core == "imaging")
        )})
        allowed.add(decision_digest(fixture))
    if decision_digest(context) not in allowed:
        raise ValueError("Mocks accept only the fixed synthetic fixture.")


class _MockCoreAdapter:
    core: str

    def __init__(self, *, now: datetime | None = None):
        self.now = now or datetime.now(timezone.utc)

    def current_version(self) -> ComponentVersion:
        return ComponentVersion(component_id=f"synthetic-{self.core}-mock", version="1.0.0",
                                artifact_sha256=decision_digest(synthetic_core_input()), kind="adapter")

    def collect(self, context: CoreInput) -> CoreOutput:
        _synthetic_guard(context, self.core)
        return CoreOutput(
            core=self.core, visit_id=context.visit_id,
            clinical_context_sha256=context.clinical_context_sha256,
            component=self.current_version(), generated_at=self.now,
            valid_until=self.now + timedelta(hours=1), status="available",
            findings=tuple(CoreFinding(
                finding_id=f"synthetic-{self.core}-{index}", source=item.source,
                observation=item.observation.model_dump(mode="json"), origin="record",
            ) for index, item in enumerate(context.observations)
                if (item.observation.category == "imaging") == (self.core == "imaging")),
        )


class MockOrthopedicAdapter(_MockCoreAdapter):
    """Synthetic passthrough only; contains no orthopedic inference."""

    core = "orthopedic"


class MockImagingAdapter(_MockCoreAdapter):
    """Synthetic report passthrough only; no image processing or DICOM identity."""

    core = "imaging"


class MockDecisionAdapter:
    """A fabricated research score; never registered for production records."""

    def __init__(self, *, now: datetime | None = None):
        self.now = now or datetime.now(timezone.utc)

    def current_version(self) -> ComponentVersion:
        return ComponentVersion(component_id="synthetic-decision-mock", version="1.0.0",
                                artifact_sha256=decision_digest(synthetic_core_input()), kind="model")

    def collect(self, context: CoreInput) -> DecisionModelResult:
        _synthetic_guard(context)
        return DecisionModelResult(
            result_id="synthetic-decision-result", visit_id=context.visit_id,
            clinical_context_sha256=context.clinical_context_sha256, component=self.current_version(),
            source_references=tuple(item.source for item in context.observations),
            generated_at=self.now, valid_until=self.now + timedelta(hours=1),
            signals=(DecisionSignal(code="research_score", value=0.5),),
            limitations=("Fabricated score; no model was trained, evaluated, or clinically validated.",),
        )
