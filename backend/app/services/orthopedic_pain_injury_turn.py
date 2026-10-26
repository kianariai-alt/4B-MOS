"""Compose the existing adaptive turn with the source-organized review.

No second answer resolver, question selector or safety engine is introduced.
"""
import hashlib
from pathlib import Path

from backend.app.schemas import orthopedic_pain_injury_turn as turn_schema
from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.schemas.orthopedic_pain_injury_turn import KneePainInjuryTurn
from backend.app.schemas.orthopedic_workbench_turn import KneeWorkbenchTurnRequest
from backend.app.services.orthopedic_pain_injury import build_knee_pain_injury_review
from backend.app.services.orthopedic_workbench_turn import apply_knee_workbench_turn


def apply_knee_pain_injury_turn(request: KneeWorkbenchTurnRequest | dict) -> KneePainInjuryTurn:
    request = KneeWorkbenchTurnRequest.model_validate(
        request.model_dump(mode="json") if isinstance(request, KneeWorkbenchTurnRequest) else request
    )
    turn = apply_knee_workbench_turn(request)
    review = build_knee_pain_injury_review(turn.state)
    if review.workbench != turn.workbench:
        raise ValueError("Pain/injury organization must preserve the underlying clinical workbench.")
    next_item = turn.next_patient_question
    linked = tuple(route.id for route in review.routes
                   if next_item is not None and any(item.id == next_item.id for item in route.question_links))
    result = KneePainInjuryTurn(
        state=turn.state, review=review, next_patient_question=next_item,
        next_question_route_ids=linked, prior_state_sha256=turn.prior_state_sha256,
        turn_result_sha256=turn.result_sha256, request_sha256=turn.request_sha256,
        rules_sha256=content_digest({
            "version": "1.0.0", "turn_rules_sha256": turn.rules_sha256,
            "review_rules_sha256": review.rules_sha256,
            "service_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "schema_sha256": hashlib.sha256(Path(turn_schema.__file__).read_bytes()).hexdigest(),
        }), result_sha256="0" * 64,
    )
    return result.model_copy(update={
        "result_sha256": content_digest(result.model_dump(mode="json", exclude={"result_sha256"})),
    })
