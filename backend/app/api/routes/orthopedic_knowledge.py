"""Opt-in physician authoring preview; never attaches drafts to patient records."""
from fastapi import APIRouter, Depends, HTTPException, Response

from backend.app.api.dependencies import require_roles
from backend.app.core.config import settings
from backend.app.models.user import User
from backend.app.schemas.orthopedic_adapter import OrthopedicDecisionKnowledge
from backend.app.schemas.orthopedic_knowledge import KneeKnowledgePack
from backend.app.schemas.orthopedic_questions import OrthopedicQuestionContext
from backend.app.services.orthopedic_adapter import build_decision_knowledge
from backend.app.services.orthopedic_knowledge import load_knee_pack


def require_preview_enabled() -> None:
    if not settings.ORTHOPEDIC_PREVIEW_ENABLED:
        raise HTTPException(status_code=404, detail="Orthopedic authoring preview is disabled.")


router = APIRouter(
    prefix="/knowledge/orthopedics/knee", tags=["Orthopedic Knowledge Preview"],
    dependencies=[Depends(require_preview_enabled)],
)


@router.get("", response_model=KneeKnowledgePack)
def get_knee_pack(
    response: Response, _actor: User = Depends(require_roles("admin", "physician")),
) -> KneeKnowledgePack:
    response.headers["Cache-Control"] = "no-store"
    return load_knee_pack()


@router.post("/preview", response_model=OrthopedicDecisionKnowledge)
def preview_knee_questions(
    context: OrthopedicQuestionContext, response: Response,
    _actor: User = Depends(require_roles("admin", "physician")),
) -> OrthopedicDecisionKnowledge:
    response.headers["Cache-Control"] = "no-store"
    return build_decision_knowledge(context)
