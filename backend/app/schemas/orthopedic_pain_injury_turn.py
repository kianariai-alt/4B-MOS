"""Additive adaptive-turn response with a Zetamed-organized clinical review."""
from typing import Literal

from pydantic import field_validator

from backend.app.schemas.orthopedic_interview_tree import DraftTreeModel
from backend.app.schemas.orthopedic_knowledge import Digest
from backend.app.schemas.orthopedic_pain_injury import KneePainInjuryReview
from backend.app.schemas.orthopedic_workbench import KneeWorkbenchRequest, WorkbenchNextItem


class KneePainInjuryTurn(DraftTreeModel):
    schema_id: Literal["4b-mos.knee-pain-injury-turn"] = "4b-mos.knee-pain-injury-turn"
    schema_version: Literal["1.0.0"] = "1.0.0"
    state: KneeWorkbenchRequest
    review: KneePainInjuryReview
    next_patient_question: WorkbenchNextItem | None
    next_question_route_ids: tuple[str, ...]
    prior_state_sha256: Digest
    turn_result_sha256: Digest
    request_sha256: Digest
    rules_sha256: Digest
    result_sha256: Digest
    registry_write_performed: Literal[False] = False
    authenticated_provenance: Literal[False] = False

    @field_validator("registry_write_performed", "authenticated_provenance", mode="before")
    @classmethod
    def exact_false(cls, value):
        if type(value) is not bool or value is not False:
            raise ValueError("An authoring turn cannot write or authenticate clinical provenance.")
        return value
