"""Portable file and approved-style contracts are explicitly versioned."""
import json
from pathlib import Path

import pytest

from backend.app.schemas.visit_learning import VisitLearningPacket
from backend.app.schemas.interview_style import ApprovedInterviewStyle


@pytest.mark.parametrize("name,model", [
    ("visit-learning-packet", VisitLearningPacket), ("approved-interview-style", ApprovedInterviewStyle),
])
def test_published_schema_matches_current_model(name, model):
    path = Path(__file__).resolve().parents[2] / "docs/contracts" / (name + "-1.0.0.schema.json")
    assert json.loads(path.read_text(encoding="utf-8")) == model.model_json_schema()
