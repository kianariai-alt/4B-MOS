from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


Sha256 = str
DecisionType = Literal[
    "select_option",
    "modify_option",
    "combine_options",
    "choose_outside_roadmap",
    "defer",
    "no_treatment",
]
ProtocolSource = Literal[
    "roadmap_option",
    "outside_roadmap",
]


class DecisionProtocolReference(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    protocol_code: str = Field(min_length=1, max_length=100)
    protocol_version: str = Field(min_length=1, max_length=30)
    treatment_type: str = Field(min_length=1, max_length=50)
    source: ProtocolSource


class TreatmentDecisionCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    expected_clinical_context_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_roadmap_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_previous_decision_sha256: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    decision_type: DecisionType
    selected_protocols: list[DecisionProtocolReference] = Field(
        default_factory=list,
        max_length=5,
    )
    rationale: str = Field(min_length=10, max_length=5000)
    modification_summary: str | None = Field(
        default=None,
        min_length=5,
        max_length=5000,
    )
    patient_preference_summary: str | None = Field(
        default=None,
        max_length=5000,
    )
    evidence_brief_ids: list[str] = Field(
        default_factory=list,
        max_length=20,
    )

    @model_validator(mode="after")
    def validate_decision_shape(self):
        unique_refs = {
            (
                item.protocol_code,
                item.protocol_version,
                item.treatment_type,
                item.source,
            )
            for item in self.selected_protocols
        }
        if len(unique_refs) != len(self.selected_protocols):
            raise ValueError("Selected protocol references must be unique.")

        count = len(self.selected_protocols)
        roadmap_refs = all(
            item.source == "roadmap_option"
            for item in self.selected_protocols
        )
        outside_refs = all(
            item.source == "outside_roadmap"
            for item in self.selected_protocols
        )

        if self.decision_type == "select_option":
            if count != 1 or not roadmap_refs:
                raise ValueError(
                    "select_option requires exactly one roadmap option."
                )
            if self.modification_summary is not None:
                raise ValueError(
                    "select_option cannot include modification_summary."
                )
        elif self.decision_type == "modify_option":
            if count != 1 or not roadmap_refs:
                raise ValueError(
                    "modify_option requires exactly one roadmap option."
                )
            if not self.modification_summary:
                raise ValueError(
                    "modify_option requires modification_summary."
                )
        elif self.decision_type == "combine_options":
            if count < 2 or not roadmap_refs:
                raise ValueError(
                    "combine_options requires at least two roadmap options."
                )
            if not self.modification_summary:
                raise ValueError(
                    "combine_options requires modification_summary."
                )
        elif self.decision_type == "choose_outside_roadmap":
            if count != 1 or not outside_refs:
                raise ValueError(
                    "choose_outside_roadmap requires exactly one outside "
                    "protocol reference."
                )
        elif self.decision_type in {"defer", "no_treatment"}:
            if count:
                raise ValueError(
                    "defer and no_treatment cannot select protocols."
                )
            if self.modification_summary is not None:
                raise ValueError(
                    "defer and no_treatment cannot include a protocol "
                    "modification summary."
                )

        if len(self.evidence_brief_ids) != len(set(self.evidence_brief_ids)):
            raise ValueError("evidence_brief_ids must be unique.")
        return self


class TreatmentDecisionPayloadRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    id: str
    visit_id: str
    supersedes_decision_id: str | None
    supersedes_decision_sha256: str | None
    decision_type: DecisionType
    clinical_context_sha256: str
    roadmap_sha256: str
    roadmap_snapshot: dict
    selected_protocols: list[DecisionProtocolReference]
    rationale: str
    modification_summary: str | None
    patient_preference_summary: str | None
    evidence_brief_ids: list[str]
    evidence_brief_sha256s: list[str]
    decided_by_user_id: str
    decided_at: str
    decision_is_physician_authored: Literal[True] = True
    roadmap_was_not_ranked: Literal[True] = True
    requires_independent_clinical_judgment: Literal[True] = True


class TreatmentDecisionRead(BaseModel):
    id: str
    visit_id: str
    supersedes_decision_id: str | None
    decision_type: DecisionType
    clinical_context_sha256: str
    roadmap_sha256: str
    selected_protocols: list[DecisionProtocolReference]
    rationale: str
    modification_summary: str | None
    patient_preference_summary: str | None
    evidence_brief_ids: list[str]
    decided_by_user_id: str
    sha256: str
    decided_at: datetime
    payload: TreatmentDecisionPayloadRead
    is_current_decision: bool
    linked_treatment_ids: list[str] = Field(default_factory=list)
    linked_outcome_ids: list[str] = Field(default_factory=list)
    is_system_selected: Literal[False] = False
    is_prescription_generated_by_system: Literal[False] = False
