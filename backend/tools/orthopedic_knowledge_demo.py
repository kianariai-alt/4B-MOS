"""Offline synthetic preview and reproducible schemas; no database/network calls.

Run from the repository root:
  python -m backend.tools.orthopedic_knowledge_demo
  python -m backend.tools.orthopedic_knowledge_demo --write-artifacts
"""
import argparse
import json
from pathlib import Path

from backend.app.schemas.orthopedic_adapter import OrthopedicDecisionKnowledge
from backend.app.schemas.orthopedic_knowledge import KneeKnowledgePack
from backend.app.schemas.orthopedic_questions import OrthopedicQuestionContext
from backend.app.services.orthopedic_adapter import build_decision_knowledge
from backend.app.services.orthopedic_knowledge import load_knee_pack


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-artifacts", action="store_true")
    args = parser.parse_args()
    pack = load_knee_pack()
    context = OrthopedicQuestionContext.model_validate({
        "body_region": "knee",
        "observations": [
            {"field": "onset", "state": "confirmed", "value": "gradual",
             "provenance": "patient_report", "source_ref": "synthetic:intake-v1"},
            {"field": "pain_score", "state": "confirmed", "value": 6,
             "provenance": "patient_report", "source_ref": "synthetic:intake-v1"},
            {"field": "imaging_kl_grade", "state": "unverified", "value": 2,
             "provenance": "unreviewed_imaging", "source_ref": "synthetic:report-v1"},
        ],
    })
    result = build_decision_knowledge(context, pack)
    if args.write_artifacts:
        root = Path(__file__).resolve().parents[2]
        artifacts = {
            "contracts/orthopedic-decision-knowledge-1.0.0.schema.json": OrthopedicDecisionKnowledge.model_json_schema(),
            "contracts/orthopedic-knee-pack-1.0.0.schema.json": KneeKnowledgePack.model_json_schema(),
            "contracts/orthopedic-question-context-1.0.0.schema.json": OrthopedicQuestionContext.model_json_schema(),
            "examples/orthopedic-knee-synthetic-preview.json": result.model_dump(mode="json"),
        }
        for name, payload in artifacts.items():
            target = root / "docs" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "pack_key": pack.pack_key, "draft_fact_count": len(pack.facts),
        "approved_fact_count": 0, "pack_manifest_sha256": pack.manifest_sha256,
        "synthetic_context_sha256": result.context_sha256,
        "question_rule_sha256": result.question_rules_sha256,
        "question_fields": [item.field for item in result.question_candidates],
        "review_reasons": result.review_reasons,
        "is_clinically_validated": False,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
