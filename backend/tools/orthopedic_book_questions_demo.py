"""Run eight synthetic book-aware question previews; no writes or network calls.

Run from the repository root:
    python -B -m backend.tools.orthopedic_book_questions_demo
Only synthetic case summaries, field names, references and hashes are printed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.schemas.orthopedic_book_questions import BookQuestionPreviewRequest
from backend.app.services.orthopedic_book_questions import build_book_question_preview


CASES_PATH = Path(__file__).resolve().parents[2] / 'docs/examples/orthopedic-book-question-cases-v1.json'


def run_synthetic_cases(path: Path = CASES_PATH) -> dict:
    fixture = json.loads(Path(path).read_text(encoding='utf-8'))
    if (fixture.get('schema_id') != '4b-mos.book-question-synthetic-cases'
            or fixture.get('schema_version') != '1.0.0' or fixture.get('synthetic_only') is not True
            or fixture.get('is_clinically_validated') is not False or len(fixture.get('cases', [])) != 8):
        raise ValueError('Expected the versioned eight-case synthetic fixture.')
    summaries = []
    for case in fixture['cases']:
        request = BookQuestionPreviewRequest.model_validate(case['request'])
        result = build_book_question_preview(request)
        fields = {item.field for item in result.baseline.question_candidates}
        clarify = {item.field for item in result.baseline.question_candidates
                   if item.action == 'physician_clarification'}
        sources = {item.candidate_key for item in result.source_references}
        expected = case['expected']
        if (sources != set(expected['book_candidate_keys'])
                or fields & set(expected['absent_question_fields'])
                or not set(expected['physician_clarification_fields']) <= clarify
                or not set(expected['baseline_review_reasons']) <= set(result.baseline.review_reasons)):
            raise ValueError(f"Synthetic expectation failed: {case['id']}")
        summaries.append(dict(
            id=case['id'], passed=True, description_fa=case['description_fa'],
            question_fields=[item.field for item in result.baseline.question_candidates],
            book_question_fields=[item.field for item in result.question_annotations],
            clinician_review_candidate_keys=sorted({key for card in result.clinician_review_requirements
                                                    for key in card.candidate_keys}),
            book_source_candidate_keys=sorted(sources),
            review_reasons=list(result.review_reasons),
            result_sha256=result.result_sha256,
        ))
    return dict(schema_id='4b-mos.book-question-demo-summary', schema_version='1.0.0',
                synthetic_only=True, case_count=len(summaries), passed_cases=len(summaries),
                approved_fact_count=0, registry_write_performed=False,
                is_clinically_validated=False, is_clinical_clearance=False, cases=summaries)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=CASES_PATH)
    args = parser.parse_args(argv)
    print(json.dumps(run_synthetic_cases(args.cases), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
