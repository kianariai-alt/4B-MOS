"""Export JSON Schema without database, secrets, clinical content or activation."""
import argparse
import json
from pathlib import Path

from backend.app.schemas.interview_summary import InterviewAssistantSummary
from backend.app.schemas.patient_portal import PortalAnswerCreate
from backend.app.schemas.physician_questions import BankContent


def contract():
    return {
        "contract_version": "1.0.0",
        "clinical_status": "patient_reported_requires_clinician_review",
        "question_bank": BankContent.model_json_schema(),
        "answer_command": PortalAnswerCreate.model_json_schema(),
        "assistant_summary": InterviewAssistantSummary.model_json_schema(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = json.dumps(contract(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(data, encoding="utf-8")
    else:
        print(data, end="")


if __name__ == "__main__":
    main()
