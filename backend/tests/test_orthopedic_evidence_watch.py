"""Metadata-discovery checks use explicitly synthetic provider responses."""
import hashlib
import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError

from backend.app.schemas.orthopedic_evidence_watch import EvidenceCandidate, EvidenceWatchRequest, EvidenceWatchResult
from backend.app.schemas.orthopedic_knowledge import content_digest
from backend.app.services import orthopedic_evidence_watch as watch
from backend.tools import orthopedic_evidence_watch as cli


TIME = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


def metadata(**updates):
    record = {"source": "MED", "id": "12345678", "title": "Synthetic metadata fixture, not a medical source",
              "doi": "10.0000/synthetic-fixture", "firstPublicationDate": "2025-01-01", "pubYear": "2025"}
    record.update(updates)
    return json.dumps({"version": "6.9", "hitCount": 99, "resultList": {"result": [record]}}).encode()


def test_discovery_is_network_opt_in_and_default_is_read_only():
    def forbidden(_url):
        pytest.fail("No transport should be called without --online.")
    result = watch.discover_sources({"topic": "knee_oa"}, transport=forbidden)
    assert result.status == "online_not_requested"
    assert result.acquisition_mode == "not_requested"
    assert result.fetched_at is None and result.source_payload_sha256 is None
    assert result.candidates == ()
    assert not result.registry_import_performed and not result.medical_approval_performed
    assert result.approved_fact_count == 0


@pytest.mark.parametrize("payload", [
    {"topic": "patient pain text"}, {"topic": "knee_oa", "patient_id": "any"},
    {"topic": "knee_oa", "query": "private narrative"}, {"topic": "knee_oa", "url": "http://localhost"},
    {"topic": "knee_oa", "max_records": 21}, {"topic": "knee_oa", "max_records": 0},
    {"topic": "knee_oa", "max_records": True}, {"topic": "knee_oa", "since": "2026-01-01] OR private"},
])
def test_request_has_no_arbitrary_query_url_or_patient_channel(payload):
    with pytest.raises(ValidationError):
        watch.discover_sources(payload)


@pytest.mark.parametrize("topic", ["knee_oa", "meniscus", "cartilage", "orthobiologics"])
def test_each_closed_topic_builds_fixed_host_lite_request(topic):
    request = EvidenceWatchRequest(topic=topic, since="2025-01-01", max_records=3)
    parsed = urlsplit(watch.request_url(request))
    assert parsed.scheme == "https" and parsed.netloc == "www.ebi.ac.uk"
    assert parsed.path == "/europepmc/webservices/rest/search"
    params = parse_qs(parsed.query)
    assert params["format"] == ["json"] and params["resultType"] == ["lite"]
    assert params["pageSize"] == ["3"] and params["cursorMark"] == ["*"]
    assert params["query"][0].startswith("SRC:MED AND ")
    assert "FIRST_PDATE:[2025-01-01 TO *]" in params["query"][0]
    assert params["query"][0].endswith(" sort_date:y")


def test_metadata_retains_citation_without_exporting_abstract_or_claiming_source_version():
    raw = metadata(abstractText="Do not export this source text", version="article version unverified",
                   isRetracted="Y", isCorrection="N")
    result = watch.parse_metadata_response({"topic": "knee_oa"}, raw, fetched_at=TIME)
    assert result.status == "discovered" and result.acquisition_mode == "provided_response"
    item, = result.candidates
    assert item.pmid == "12345678" and item.citation_url == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
    assert item.first_publication_date_reported == "2025-01-01"
    assert not item.publication_date_precision_verified
    assert item.source_version is None and not item.source_version_verified
    assert item.retraction_status == "flagged" and item.correction_status == "not_flagged_by_returned_metadata"
    assert item.evidence_quality == "unassessed" and item.status == "draft"
    assert item.independent_review_required and not item.is_clinical_recommendation
    assert result.provider_api_version == "6.9"
    assert "Do not export" not in result.model_dump_json() and "abstractText" not in result.model_dump_json()
    assert result.source_payload_sha256 == hashlib.sha256(raw).hexdigest()
    record = json.loads(raw)["resultList"]["result"][0]
    assert item.record_payload_sha256 == content_digest(record)
    assert result.result_sha256 == content_digest(result.model_dump(mode="json", exclude={"result_sha256"}))


def test_missing_status_flags_are_unknown_and_dates_are_not_invented():
    result = watch.parse_metadata_response({"topic": "meniscus"}, metadata(firstPublicationDate=None, doi=None), fetched_at=TIME)
    item = result.candidates[0]
    assert item.first_publication_date_reported is None and item.doi is None
    assert item.retraction_status == item.correction_status == "not_reported"


def test_provider_publication_types_are_retained_without_inferring_design_or_eligibility():
    raw = metadata(pubType="Journal Article; Bibliometric Analysis")
    result = watch.parse_metadata_response({"topic": "knee_oa"}, raw, fetched_at=TIME)
    item = result.candidates[0]
    assert item.publication_types_reported == "Journal Article; Bibliometric Analysis"
    assert item.evidence_quality == "unassessed" and item.independent_review_required
    assert any("do not verify each study design" in note for note in result.limitations)
    absent = watch.parse_metadata_response({"topic": "knee_oa"}, metadata(), fetched_at=TIME)
    assert absent.candidates[0].publication_types_reported is None


def test_numeric_status_flags_are_not_coerced_into_evidence():
    result = watch.parse_metadata_response({"topic": "meniscus"}, metadata(isRetracted=1, isCorrection=0), fetched_at=TIME)
    assert result.candidates[0].retraction_status == result.candidates[0].correction_status == "not_reported"


def test_digests_bind_request_metadata_and_rules_but_timestamp_is_explicit():
    one = watch.parse_metadata_response({"topic": "meniscus"}, metadata(), fetched_at=TIME)
    same = watch.parse_metadata_response({"topic": "meniscus"}, metadata(), fetched_at=TIME)
    changed = watch.parse_metadata_response({"topic": "meniscus"}, metadata(title="Different synthetic title"), fetched_at=TIME)
    assert one == same
    assert one.request_sha256 == changed.request_sha256
    assert one.rules_sha256 == changed.rules_sha256 == content_digest(watch.POLICY)
    assert one.source_payload_sha256 != changed.source_payload_sha256
    assert one.candidates[0].record_payload_sha256 != changed.candidates[0].record_payload_sha256
    assert one.result_sha256 != changed.result_sha256


@pytest.mark.parametrize("body,code", [
    (b"not JSON", "malformed_response"), (b"[]", "malformed_response"),
    (b'{"hitCount": true, "resultList": {"result": []}}', "malformed_response"),
    (b'{"hitCount": 0}', "malformed_response"),
    (metadata(source="PPR"), "invalid_record"), (metadata(id="../private"), "invalid_record"),
    (metadata(id="۱۲۳"), "invalid_record"), (metadata(title=""), "invalid_record"),
    (b"x" * (watch.MAX_RESPONSE_BYTES + 1), "response_limit"),
])
def test_malformed_or_unbounded_metadata_is_an_explicit_failure(body, code):
    result = watch.parse_metadata_response({"topic": "knee_oa"}, body, fetched_at=TIME)
    assert result.status == "failed" and result.error_code == code
    assert not result.candidates and result.source_payload_sha256 == hashlib.sha256(body).hexdigest()


def test_extra_and_duplicate_records_are_not_silently_accepted():
    data = json.loads(metadata())
    data["resultList"]["result"] *= 2
    raw = json.dumps(data).encode()
    excess = watch.parse_metadata_response({"topic": "meniscus", "max_records": 1}, raw, fetched_at=TIME)
    duplicate = watch.parse_metadata_response({"topic": "meniscus", "max_records": 2}, raw, fetched_at=TIME)
    assert excess.error_code == "response_limit" and duplicate.error_code == "invalid_record"
    assert not excess.candidates and not duplicate.candidates


@pytest.mark.parametrize("exception,code", [
    (TimeoutError(), "timeout"), (URLError("sensitive transport detail not shown"), "network_error"),
    (URLError(TimeoutError()), "timeout"),
    (HTTPError("url", 403, "Forbidden", {}, None), "http_error"),
    (HTTPError("url", 302, "Found", {}, None), "redirect_blocked"),
])
def test_failed_network_never_becomes_cached_success_or_leaks_exception_text(exception, code):
    def fail(_url):
        raise exception
    result = watch.discover_sources({"topic": "cartilage"}, online=True, transport=fail, now=lambda: TIME)
    assert result.status == "failed" and result.error_code == code and not result.candidates
    assert result.source_payload_sha256 is None and result.fetched_at is None
    assert "sensitive" not in result.model_dump_json()


def test_default_transport_uses_timeout_bounds_and_blocked_redirect_opener(monkeypatch):
    captured = {}
    class Response:
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def geturl(self): return captured["url"]
        def read(self, limit):
            captured["limit"] = limit
            return metadata()
    class Opener:
        def open(self, request, *, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return Response()
    def opener(handler):
        assert isinstance(handler, watch._BlockRedirects)
        with pytest.raises(watch.EvidenceWatchError) as exc:
            handler.redirect_request(None, None, 302, "Found", {}, "https://localhost/private")
        assert exc.value.code == "redirect_blocked"
        return Opener()
    monkeypatch.setattr(watch, "build_opener", opener)
    result = watch.discover_sources({"topic": "cartilage"}, online=True, now=lambda: TIME)
    assert result.status == "discovered" and result.acquisition_mode == "online"
    assert result.fetched_at == TIME
    assert captured["limit"] == watch.MAX_RESPONSE_BYTES + 1
    assert captured["timeout"] == watch.TIMEOUT_SECONDS


@pytest.mark.parametrize("url", [
    "http://www.ebi.ac.uk/europepmc/webservices/rest/search", "https://localhost/private",
    "https://www.ebi.ac.uk.evil.test/europepmc/webservices/rest/search",
    "https://www.ebi.ac.uk@evil.test/europepmc/webservices/rest/search",
    "https://www.ebi.ac.uk/europepmc/webservices/rest/search#redirect",
    "https://www.ebi.ac.uk/another/path",
])
def test_private_transport_also_rejects_arbitrary_endpoint_before_network(monkeypatch, url):
    monkeypatch.setattr(watch, "build_opener", lambda *_args: pytest.fail("An arbitrary endpoint must not be opened."))
    with pytest.raises(watch.EvidenceWatchError) as exc:
        watch._read_online(url)
    assert exc.value.code == "endpoint_blocked"


def test_successful_zero_hit_response_is_distinct_from_failure():
    raw = b'{"hitCount":0,"resultList":{"result":[]}}'
    result = watch.parse_metadata_response({"topic": "meniscus"}, raw, fetched_at=TIME)
    assert result.status == "discovered" and result.provider_hit_count == 0 and result.candidates == ()


@pytest.mark.parametrize("declared,expected", [("512001", "response_limit"), ("invalid", "malformed_response"), ("-1", "malformed_response")])
def test_transport_rejects_invalid_or_excessive_content_length_before_reading(monkeypatch, declared, expected):
    request = EvidenceWatchRequest(topic="meniscus")
    class Response:
        headers = {"Content-Length": declared}
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def geturl(self): return watch.request_url(request)
        def read(self, _limit): pytest.fail("Invalid declared response must not be read.")
    class Opener:
        def open(self, *_args, **_kwargs): return Response()
    monkeypatch.setattr(watch, "build_opener", lambda _handler: Opener())
    result = watch.discover_sources(request, online=True)
    assert result.status == "failed" and result.error_code == expected
    assert result.source_payload_sha256 is None


def test_naive_acquisition_time_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        watch.parse_metadata_response({"topic": "meniscus"}, metadata(), fetched_at=datetime(2026, 1, 1))


@pytest.mark.parametrize("field,value", [("medical_approval_performed", True), ("patient_information_sent", 0),
                                          ("registry_import_performed", True), ("approved_fact_count", False)])
def test_governance_is_strict_and_cannot_be_overridden(field, value):
    payload = watch.discover_sources({"topic": "meniscus"}).model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        EvidenceWatchResult.model_validate(payload)


def test_candidate_review_flags_cannot_be_overridden():
    candidate = watch.parse_metadata_response({"topic": "meniscus"}, metadata(), fetched_at=TIME).candidates[0]
    with pytest.raises(ValidationError):
        EvidenceCandidate.model_validate({**candidate.model_dump(), "independent_review_required": False})


def test_cli_without_online_prints_metadata_plan_without_creating_a_file(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["--topic", "meniscus"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "online_not_requested" and payload["candidates"] == []
    assert list(tmp_path.iterdir()) == []


def test_cli_returns_failure_exit_code_and_json_without_writing(capsys, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    def failure(request, *, online):
        return watch.discover_sources(request, online=online,
                                      transport=lambda _url: (_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(cli, "discover_sources", failure)
    assert cli.main(["--topic", "knee_oa", "--online", "--max-records", "1"]) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "timeout"
    assert list(tmp_path.iterdir()) == []
