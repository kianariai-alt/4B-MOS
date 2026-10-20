"""Research-only decision-model boundary; no diagnostic or prescribing authority.

This additive exchange reuses Unified Clinical Data Contract 1.0.0 references.
A producer cannot attest to physician verification or alter Safety outcomes.
"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from backend.app.schemas.clinical_integration import (
    ComponentVersion, ContractModel, Digest, Identifier, KnowledgeReference, RecordReference,
)


def decision_digest(model: ContractModel) -> str:
    """Canonical JSON digest, not a signature or a clinical-validity guarantee."""
    value = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DecisionSignal(ContractModel):
    """Only bounded research/input-quality scores are supported in this release."""

    code: Literal["input_completeness", "input_consistency", "research_score"]
    value: float = Field(ge=0, le=1, allow_inf_nan=False)
    interpretation: Literal["not_clinically_validated"] = "not_clinically_validated"


class DecisionModelResult(ContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    result_id: Identifier
    visit_id: Identifier
    clinical_context_sha256: Digest
    component: ComponentVersion
    source_references: tuple[RecordReference, ...] = Field(min_length=1, max_length=1000)
    knowledge: tuple[KnowledgeReference, ...] = Field(default=(), max_length=50)
    generated_at: AwareDatetime
    valid_until: AwareDatetime
    signals: tuple[DecisionSignal, ...] = Field(min_length=1, max_length=3)
    limitations: tuple[Annotated[str, Field(min_length=1, max_length=500)], ...] = Field(
        min_length=1, max_length=30,
    )
    origin: Literal["ai_generated"] = "ai_generated"
    review_status: Literal["unverified"] = "unverified"
    usable_as_confirmed_finding: Literal[False] = False
    is_diagnosis: Literal[False] = False
    is_recommendation: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    authorizes_treatment: Literal[False] = False

    @model_validator(mode="after")
    def producer_shape(self):
        if self.component.kind != "model":
            raise ValueError("Decision output requires model provenance.")
        if self.valid_until <= self.generated_at:
            raise ValueError("Decision validity must end after generation.")
        source_keys = [decision_digest(item) for item in self.source_references]
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("Decision source references must be unique.")
        codes = [signal.code for signal in self.signals]
        if len(codes) != len(set(codes)):
            raise ValueError("Decision signal codes must be unique.")
        fact_ids = [item.fact_id for item in self.knowledge]
        if len(fact_ids) != len(set(fact_ids)):
            raise ValueError("Knowledge references must be unique.")
        return self


class DecisionModelReference(ContractModel):
    """Consumer-owned validation result; model output always remains unverified."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["available", "missing", "unavailable", "invalid", "expired"]
    component: ComponentVersion | None = None
    result: DecisionModelResult | None = None
    result_sha256: Digest | None = None
    issue_codes: tuple[Identifier, ...] = ()
    usable_as_confirmed_finding: Literal[False] = False
    is_clinical_clearance: Literal[False] = False
    authorizes_treatment: Literal[False] = False

    @model_validator(mode="after")
    def validated_shape(self):
        if self.status == "available":
            if (self.result is None or self.component != self.result.component
                    or self.result_sha256 != decision_digest(self.result)):
                raise ValueError("Available decisions require matching provenance and digest.")
        elif self.result is not None or self.result_sha256 is not None:
            raise ValueError("Excluded decisions cannot expose usable model output.")
        if self.status != "available" and not self.issue_codes:
            raise ValueError("Excluded decisions require an explicit reason.")
        return self
