"""Opt-in physician authoring preview; never attaches drafts to patient records."""
from fastapi import APIRouter, Depends, HTTPException, Response

from backend.app.api.dependencies import require_roles
from backend.app.core.config import settings
from backend.app.models.user import User
from backend.app.schemas.orthopedic_adapter import OrthopedicDecisionKnowledge
from backend.app.schemas.orthopedic_knowledge import KneeKnowledgePack
from backend.app.schemas.orthopedic_questions import OrthopedicQuestionContext
from backend.app.schemas.orthopedic_book_questions import BookQuestionPreview, BookQuestionPreviewRequest
from backend.app.schemas.orthopedic_interview_tree import (
    KneeInterviewTree, KneeInterviewTreePreview, KneeInterviewTreePreviewRequest,
)
from backend.app.schemas.orthopedic_assessment import KneeAssessmentPreview
from backend.app.schemas.orthopedic_reasoning_review import KneeReasoningReview
from backend.app.services.orthopedic_adapter import build_decision_knowledge
from backend.app.services.orthopedic_book_questions import build_book_question_preview
from backend.app.services.orthopedic_knowledge import load_knee_pack
from backend.app.services.orthopedic_interview_tree import (
    build_interview_tree, build_interview_tree_preview,
)
from backend.app.services.orthopedic_assessment import build_knee_assessment
from backend.app.services.orthopedic_reasoning_review import build_knee_reasoning_review


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


@router.post("/book-preview", response_model=BookQuestionPreview)
def preview_knee_book_questions(
    request: BookQuestionPreviewRequest, response: Response,
    _actor: User = Depends(require_roles("admin", "physician")),
) -> BookQuestionPreview:
    response.headers["Cache-Control"] = "no-store"
    return build_book_question_preview(request)


@router.get("/interview-tree", response_model=KneeInterviewTree)
def get_knee_interview_tree(
    response: Response, _actor: User = Depends(require_roles("admin", "physician")),
) -> KneeInterviewTree:
    response.headers["Cache-Control"] = "no-store"
    return build_interview_tree()


@router.post("/interview-tree/preview", response_model=KneeInterviewTreePreview)
def preview_knee_interview_tree(
    request: KneeInterviewTreePreviewRequest, response: Response,
    _actor: User = Depends(require_roles("admin", "physician")),
) -> KneeInterviewTreePreview:
    response.headers["Cache-Control"] = "no-store"
    return build_interview_tree_preview(request)


@router.post("/interview-tree/assessment-preview", response_model=KneeAssessmentPreview)
def preview_knee_assessment(
    request: KneeInterviewTreePreviewRequest, response: Response,
    _actor: User = Depends(require_roles("admin", "physician")),
) -> KneeAssessmentPreview:
    response.headers["Cache-Control"] = "no-store"
    return build_knee_assessment(request)


@router.post("/interview-tree/reasoning-review", response_model=KneeReasoningReview)
def review_knee_reasoning(
    request: KneeInterviewTreePreviewRequest, response: Response,
    _actor: User = Depends(require_roles("admin", "physician")),
) -> KneeReasoningReview:
    response.headers["Cache-Control"] = "no-store"
    return build_knee_reasoning_review(request)
