"""One source-preserving response and the recomputed Draft interview state.

This is a stateless authoring protocol. Respondent and provenance describe the
supplied record; they are not proof of authenticated clinical observation.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from backend.app.schemas.orthopedic_interview_tree import (
    DraftTreeModel, TreeInterviewAnswer,
)
from backend.app.schemas.orthopedic_knowledge import Digest
from backend.app.schemas.orthopedic_questions import StrictPreview, StructuredAnswer
from backend.app.schemas.orthopedic_workbench import (
    KneeWorkbench, KneeWorkbenchRequest, SupplementalObservation, WorkbenchNextItem,
)


class WorkbenchResponseEvent(StrictPreview):
    respondent: Literal["patient", "physician"] = "patient"
    observation: TreeInterviewAnswer | SupplementalObservation | StructuredAnswer
    episode_ref: str | None = Field(
        default=None, min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$",
    )

    @model_validator(mode="after")
    def segregate_respondent_and_channels(self):
        item = self.observation
        if isinstance(item, StructuredAnswer) and not item.field.startswith(("exam_", "imaging_")):
            raise ValueError("Legacy clinical answers are accepted only in examination/imaging channels.")
        if self.respondent == "patient" and item.provenance != "patient_report":
            raise ValueError("A patient response cannot record a physician examination or reviewed image.")
        episode_field = item.field in {
            "treatment_description", "treatment_pain_response", "treatment_function_response",
        }
        if episode_field != (self.episode_ref is not None):
            raise ValueError("Only treatment responses must identify one treatment episode.")
        return self


class KneeWorkbenchTurnRequest(StrictPreview):
    state: KneeWorkbenchRequest
    answer: WorkbenchResponseEvent


class KneeWorkbenchTurn(DraftTreeModel):
    schema_id: Literal["4b-mos.knee-workbench-turn"] = "4b-mos.knee-workbench-turn"
    schema_version: Literal["1.0.0"] = "1.0.0"
    state: KneeWorkbenchRequest
    workbench: KneeWorkbench
    next_patient_question: WorkbenchNextItem | None
    prior_state_sha256: Digest
    request_sha256: Digest
    rules_sha256: Digest
    result_sha256: Digest
    review_only: Literal[True] = True
    is_diagnosis: Literal[False] = False
    is_recommendation: Literal[False] = False
    registry_write_performed: Literal[False] = False
    authenticated_provenance: Literal[False] = False

    @field_validator("review_only", "is_diagnosis", "is_recommendation",
                     "registry_write_performed", "authenticated_provenance", mode="before")
    @classmethod
    def exact_flags(cls, value, info):
        expected = info.field_name == "review_only"
        if type(value) is not bool or value is not expected:
            raise ValueError("Turn governance flags require exact JSON booleans.")
        return value
