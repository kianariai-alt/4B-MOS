"""Run ten synthetic knee interview-tree previews without files, DB or network writes.

Run from the repository root:
    python -B -m backend.tools.orthopedic_interview_tree_demo

The default output contains only synthetic scenario summaries, question targets,
review reasons, source identifiers and hashes; answer text is not exported.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.schemas.orthopedic_interview_tree import InterviewTreePreviewRequest
from backend.app.services.orthopedic_interview_tree import build_interview_tree_preview


CASES_PATH = Path(__file__).resolve().parents[2] / "docs/examples/orthopedic-interview-tree-cases-v1.json"


def run_synthetic_cases(path: Path = CASES_PATH) -> dict:
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    if (fixture.get("schema_id") != "4b-mos.knee-interview-tree-synthetic-cases"
            or fixture.get("schema_version") != "1.0.0" or fixture.get("synthetic_only") is not True
            or fixture.get("is_clinically_validated") is not False or len(fixture.get("cases", [])) != 10):
        raise ValueError("Expected the versioned ten-case synthetic interview-tree fixture.")
    summaries = []
    for case in fixture["cases"]:
        request = InterviewTreePreviewRequest.model_validate(case["request"])
        before = request.model_dump(mode="json")
        result = build_interview_tree_preview(request)
        fields = {candidate.field for candidate in result.question_candidates}
        clarify = {candidate.field for candidate in result.question_candidates
                   if candidate.action == "physician_clarification"}
        targets = {(candidate.field, candidate.episode_ref) for candidate in result.question_candidates}
        expected = case["expected"]
        target_values = lambda key: {(item["field"], item.get("episode_ref"))
                                     for item in expected.get(key, [])}
        checks = (
            set(expected["required_question_fields"]) <= fields,
            not fields & set(expected["absent_question_fields"]),
            set(expected["clarification_fields"]) <= clarify,
            target_values("required_candidate_targets") <= targets,
            not target_values("absent_candidate_targets") & targets,
            all(any(part in reason for reason in result.review_reasons)
                for part in expected.get("review_reason_contains", [])),
            "candidate_count" not in expected or len(result.question_candidates) == expected["candidate_count"],
            result.context.model_dump(mode="json") == before["context"],
            request.model_dump(mode="json") == before,
            result.approved_fact_count == 0,
            result.is_clinical_clearance is False,
            result.is_diagnosis is False,
            result.is_recommendation is False,
            result.authorizes_treatment is False,
            result.registry_write_performed is False,
            result.safety_evaluation == "not_performed",
            result.governance_status == "draft",
        )
        if not all(checks):
            raise ValueError(f"Synthetic expectation failed: {case['id']}; checks={checks}")
        summaries.append(dict(
            id=case["id"], passed=True, description_fa=case["description_fa"],
            question_targets=[dict(number=candidate.number, field=candidate.field,
                                   episode_ref=candidate.episode_ref, action=candidate.action)
                              for candidate in result.question_candidates],
            information_gap_count=len(result.information_gaps),
            book_source_candidate_keys=[source.candidate_key for source in result.book_source_references],
            review_reasons=list(result.review_reasons),
            result_sha256=result.result_sha256,
        ))
    return dict(schema_id="4b-mos.knee-interview-tree-demo-summary", schema_version="1.0.0",
                synthetic_only=True, case_count=len(summaries), passed_cases=len(summaries),
                approved_fact_count=0, registry_write_performed=False,
                is_clinically_validated=False, is_clinical_clearance=False, cases=summaries)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    args = parser.parse_args(argv)
    print(json.dumps(run_synthetic_cases(args.cases), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
