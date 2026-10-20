"""Dry-run only: validate retained technical drafts against existing Registry schemas."""

import json
from pathlib import Path

from backend.app.imaging_intelligence.knowledge_drafts import prepare_registry_drafts


PACK_PATH = Path(__file__).resolve().parents[2] / "docs/knowledge/imaging-review-drafts-v1.json"


def draft_plan():
    pack = json.loads(PACK_PATH.read_text())
    return {"dry_run": True, "database_accessed": False, "approved_fact_count": 0,
            "drafts": [x.to_dict() for x in prepare_registry_drafts(pack)],
            "source_review_queue": pack["source_review_queue"]}


if __name__ == "__main__":
    print(json.dumps(draft_plan(), indent=2, sort_keys=True))
