"""Apply one offered response, preserve records, and recompute the next question.

No answer is synthesized from another answer. In particular, multi-select input
is never reduced to the first option to satisfy the legacy single-choice model.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from backend.app.schemas import orthopedic_workbench_turn as turn_schema
from backend.app.schemas.orthopedic_interview_tree import TREATMENT_FIELDS
from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.schemas.orthopedic_workbench import KneeWorkbenchRequest, SupplementalObservation
from backend.app.schemas.orthopedic_workbench_turn import (
    KneeWorkbenchTurn, KneeWorkbenchTurnRequest,
)
from backend.app.services.orthopedic_workbench import build_knee_workbench


def _offered(request: KneeWorkbenchTurnRequest, workbench):
    event = request.answer
    item = event.observation
    for candidate in workbench.next_items:
        if candidate.field != item.field:
            continue
        episode_ref = getattr(candidate, "episode_ref", None)
        new_episode = (item.field == "treatment_description" and episode_ref is None
                       and event.episode_ref not in {
                           episode.episode_ref for episode in request.state.interview.context.treatment_episodes
                       })
        if episode_ref != event.episode_ref and not new_episode:
            continue
        if candidate.action in {"not_automatically_reask", "review_existing"}:
            continue
        if event.respondent == "patient":
            if candidate.category != "patient_question" or candidate.action != "ask_missing":
                continue
        elif candidate.category == "imaging_review" and item.provenance not in {
            "reviewed_imaging", "unreviewed_imaging",
        }:
            continue
        if candidate.question and candidate.question.channel != item.provenance:
            # The existing schema separately permits unreviewed image reports;
            # they remain quarantined rather than being promoted to reviewed.
            if not (candidate.question.channel == "reviewed_imaging"
                    and item.provenance == "unreviewed_imaging"):
                continue
        return candidate
    raise ValueError("The response must address an offered item in its declared channel and episode.")


def apply_knee_workbench_turn(request: KneeWorkbenchTurnRequest | dict) -> KneeWorkbenchTurn:
    """Return a new state after one response; never mutate supplied state or stores."""
    request = KneeWorkbenchTurnRequest.model_validate(
        request.model_dump(mode="json") if isinstance(request, KneeWorkbenchTurnRequest) else request
    )
    prior = build_knee_workbench(request.state)
    _offered(request, prior)
    state = request.state.model_dump(mode="json")
    item = request.answer.observation
    payload = item.model_dump(mode="json")
    if isinstance(item, SupplementalObservation):
        destination = state["supplemental_observations"]
    elif item.field.startswith(("exam_", "imaging_")):
        destination = state["interview"]["context"]["clinical_findings"]
    elif item.field in TREATMENT_FIELDS:
        episodes = state["interview"]["context"]["treatment_episodes"]
        target = next((episode for episode in episodes
                       if episode["episode_ref"] == request.answer.episode_ref), None)
        if target is None:
            target = {"episode_ref": request.answer.episode_ref, "observations": []}
            episodes.append(target)
        destination = target["observations"]
    else:
        destination = state["interview"]["context"]["observations"]
    if any(row["field"] == item.field and row["source_ref"] == item.source_ref for row in destination):
        raise ValueError("A field/source pair is immutable; duplicate responses cannot overwrite it.")
    destination.append(payload)
    updated = KneeWorkbenchRequest.model_validate(state)
    workbench = build_knee_workbench(updated)
    next_question = None
    if workbench.workflow_status not in {"prompt_physician_review", "outside_scope", "side_specific_review"}:
        next_question = next((candidate for candidate in workbench.next_items
                              if candidate.category == "patient_question" and candidate.action == "ask_missing"
                              and candidate.question is not None), None)
    rules = content_digest({
        "version": "1.0.0",
        "service_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "schema_sha256": hashlib.sha256(Path(turn_schema.__file__).read_bytes()).hexdigest(),
        "workbench_rules_sha256": workbench.rules_sha256,
        "policy": "offered-item-only;typed-channel;append-only;preserve-multi;recompute-every-response-v1",
    })
    result = KneeWorkbenchTurn(
        state=updated, workbench=workbench, next_patient_question=next_question,
        prior_state_sha256=content_digest(request.state.model_dump(mode="json")),
        request_sha256=content_digest(request.model_dump(mode="json")), rules_sha256=rules,
        result_sha256="0" * 64,
    )
    return result.model_copy(update={
        "result_sha256": content_digest(result.model_dump(mode="json", exclude={"result_sha256"})),
    })
