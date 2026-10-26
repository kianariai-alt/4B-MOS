"""Print patient-free source-discovery JSON; no output files or clinical writes."""
import argparse
from datetime import date

from backend.app.schemas.orthopedic_evidence_watch import EvidenceWatchRequest
from backend.app.services.orthopedic_evidence_watch import discover_sources


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True, choices=("knee_oa", "meniscus", "cartilage", "orthobiologics"))
    parser.add_argument("--since", type=date.fromisoformat, help="First publication date, YYYY-MM-DD; not indexing/update date.")
    parser.add_argument("--max-records", type=int, default=10, choices=range(1, 21))
    parser.add_argument("--online", action="store_true", help="Explicitly request one bounded Europe PMC metadata page.")
    args = parser.parse_args(argv)
    request = EvidenceWatchRequest(topic=args.topic, since=args.since, max_records=args.max_records)
    result = discover_sources(request, online=args.online)
    print(result.model_dump_json(indent=2))
    return 1 if result.status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
