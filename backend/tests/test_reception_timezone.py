from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.app.services.reception import ReceptionConflictError, _read
from backend.app.services.session_finalization import evidence_digest


def reception_record():
    created = datetime(2026, 10, 13, 9, 52, 14, 967946, tzinfo=timezone.utc)
    payload = {
        "schema_version": 1, "id": "synthetic-record", "visit_id": "synthetic-visit",
        "version": 1, "request_key": "synthetic-request", "recorded_by": "synthetic-doctor",
        "created_at": created.isoformat(), "command": {"patient_reported_complaint": "Synthetic"},
    }
    return SimpleNamespace(**{key: payload[key] for key in (
        "id", "visit_id", "version", "request_key", "recorded_by"
    )}, created_at=created, payload=payload, sha256=evidence_digest(payload))


@pytest.mark.parametrize("offset", [0, 3.5, -5])
def test_same_reception_instant_in_different_database_timezones(offset):
    record = reception_record()
    record.created_at = record.created_at.astimezone(timezone(timedelta(hours=offset)))
    assert _read(record).version == 1


def test_sqlite_naive_reception_timestamp_remains_utc():
    record = reception_record()
    record.created_at = record.created_at.replace(tzinfo=None)
    assert _read(record).version == 1


def test_timezone_fix_does_not_accept_a_different_instant_or_changed_payload():
    record = reception_record()
    record.created_at += timedelta(seconds=1)
    with pytest.raises(ReceptionConflictError):
        _read(record)
    record = reception_record()
    record.payload["command"]["patient_reported_complaint"] = "Changed"
    with pytest.raises(ReceptionConflictError):
        _read(record)
