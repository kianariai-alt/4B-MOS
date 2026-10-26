"""Opt-in, bounded Europe PMC metadata discovery with no patient input or writes.

Discovery order is publication-date order, not a ranking of clinical treatments.
The existing Medical Knowledge Registry remains the only approval path.
"""
from __future__ import annotations

import hashlib
import json
import socket
from datetime import datetime, timezone
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import ValidationError

from backend.app.schemas.orthopedic_evidence_watch import (
    EvidenceCandidate, EvidenceWatchRequest, EvidenceWatchResult,
)
from backend.app.schemas.orthopedic_knowledge import content_digest


ENDPOINT = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 512_000
TOPIC_QUERIES = {
    "knee_oa": '(TITLE_ABS:"knee osteoarthritis")',
    "meniscus": '(TITLE_ABS:meniscus OR TITLE_ABS:meniscal)',
    "cartilage": '(TITLE_ABS:knee AND (TITLE_ABS:cartilage OR TITLE_ABS:osteochondral))',
    "orthobiologics": '(TITLE_ABS:knee AND (TITLE_ABS:"platelet rich plasma" OR TITLE_ABS:orthobiologics OR TITLE_ABS:exosomes OR TITLE_ABS:"mesenchymal stromal cells" OR TITLE_ABS:"stromal vascular fraction" OR TITLE_ABS:"autologous conditioned serum"))',
}
STUDY_FILTER = '(PUB_TYPE:Guideline OR PUB_TYPE:"Systematic Review" OR PUB_TYPE:"Meta-Analysis" OR PUB_TYPE:"Randomized Controlled Trial")'
POLICY = {
    "version": "1.0.0", "endpoint": ENDPOINT, "topics": TOPIC_QUERIES,
    "study_filter": STUDY_FILTER, "source": "MED", "result_type": "lite",
    "max_records": 20, "max_response_bytes": MAX_RESPONSE_BYTES,
    "timeout_seconds": TIMEOUT_SECONDS, "redirects": "blocked",
    "date_filter": "FIRST_PDATE", "order": "sort_date:y",
    "access_scope": "bibliographic_metadata_only", "approval": "never",
    "publication_type_appraisal": "not_performed",
}
RULES_SHA256 = content_digest(POLICY)
LIMITATIONS = (
    "Metadata discovery is not a systematic review, a full-text appraisal or proof of efficacy.",
    "Only the first bounded page of selected PubMed-indexed publication types is requested; indexing and publication-type omissions remain possible.",
    "Publication-type search filters do not verify each study design or eligibility; bibliometric or otherwise unsuitable records may still require exclusion during review.",
    "The date filter and order use first publication date, not indexing/update date; this does not guarantee that all recent corrections or guideline changes are found.",
    "Provider publication dates may be algorithmically completed; exact date precision and source version are not independently verified.",
    "Missing retraction/correction flags mean not reported; the returned flags are not an independent publication-status review.",
    "All candidates require source, population, methods, conflicts, status and independent clinical review before any Registry approval or clinical use.",
)


class EvidenceWatchError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class _BlockRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise EvidenceWatchError("redirect_blocked", "The metadata endpoint attempted a redirect; no redirect was followed.")


def build_query(request: EvidenceWatchRequest) -> str:
    query = f"SRC:MED AND {TOPIC_QUERIES[request.topic]} AND {STUDY_FILTER}"
    if request.since:
        query += f" AND FIRST_PDATE:[{request.since.isoformat()} TO *]"
    return query + " sort_date:y"


def request_url(request: EvidenceWatchRequest) -> str:
    return ENDPOINT + "?" + urlencode({
        "query": build_query(request), "format": "json", "resultType": "lite",
        "pageSize": request.max_records, "cursorMark": "*",
    })


def _read_online(url: str) -> bytes:
    # Only URLs produced by request_url reach this private transport. The opener
    # retains the inherited proxy and default TLS verification; no credentials,
    # user URL, follow-up links or article bodies are requested.
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.netloc != "www.ebi.ac.uk"
            or parts.path != "/europepmc/webservices/rest/search" or parts.fragment):
        raise EvidenceWatchError("endpoint_blocked", "Only the fixed HTTPS Europe PMC metadata endpoint is permitted.")
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "4B-MOS-Evidence-Discovery/1.0"})
    with build_opener(_BlockRedirects()).open(request, timeout=TIMEOUT_SECONDS) as response:
        if response.geturl() != url:
            raise EvidenceWatchError("redirect_blocked", "Unexpected final metadata URL.")
        length = response.headers.get("Content-Length")
        if length is not None:
            try:
                declared_length = int(length)
                if declared_length < 0:
                    raise EvidenceWatchError("malformed_response", "Invalid Content-Length header.")
                if declared_length > MAX_RESPONSE_BYTES:
                    raise EvidenceWatchError("response_limit", "Metadata response exceeds the configured byte limit.")
            except ValueError:
                raise EvidenceWatchError("malformed_response", "Invalid Content-Length header.") from None
        body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise EvidenceWatchError("response_limit", "Metadata response exceeds the configured byte limit.")
    return body


def _text(record: dict, key: str, *, required=False, maximum=2000) -> str | None:
    value = record.get(key)
    if value is None or value == "":
        if required:
            raise EvidenceWatchError("invalid_record", f"A metadata record is missing {key}.")
        return None
    if not isinstance(value, str) or len(value) > maximum or not value.strip():
        raise EvidenceWatchError("invalid_record", f"A metadata record has invalid {key}.")
    return value.strip()


def _flag(record: dict, key: str) -> str:
    value = record.get(key)
    if value is True or type(value) is str and value in ("Y", "y", "true"):
        return "flagged"
    if value is False or type(value) is str and value in ("N", "n", "false"):
        return "not_flagged_by_returned_metadata"
    return "not_reported"


def _candidate(record: object) -> EvidenceCandidate:
    if not isinstance(record, dict):
        raise EvidenceWatchError("invalid_record", "A metadata record is not an object.")
    identifier = _text(record, "id", required=True, maximum=30)
    if record.get("source") != "MED" or not identifier.isascii() or not identifier.isdecimal():
        raise EvidenceWatchError("invalid_record", "A metadata record does not have the requested PubMed source and identifier.")
    return EvidenceCandidate(
        candidate_id="europe_pmc:MED:" + identifier, provider_id=identifier, pmid=identifier,
        doi=_text(record, "doi", maximum=300), title=_text(record, "title", required=True),
        journal=_text(record, "journalTitle", maximum=500), publication_year=_text(record, "pubYear", maximum=10),
        publication_types_reported=_text(record, "pubType", maximum=1000),
        first_publication_date_reported=_text(record, "firstPublicationDate", maximum=30),
        # API release version is not an article/source version.
        source_version=None, citation_url="https://pubmed.ncbi.nlm.nih.gov/" + identifier + "/",
        retraction_status=_flag(record, "isRetracted"), correction_status=_flag(record, "isCorrection"),
        record_payload_sha256=content_digest(record),
    )


def _result(request, *, acquisition_mode, status, **fields):
    payload = dict(
        request=request.model_dump(mode="json"), request_sha256=content_digest(request.model_dump(mode="json")),
        rules_sha256=RULES_SHA256, query=build_query(request), endpoint=ENDPOINT,
        acquisition_mode=acquisition_mode, status=status, limitations=LIMITATIONS, **fields,
    )
    # Hash the complete normalized output (including acquisition timestamp), not
    # a partial dict with omitted governance defaults.
    result = EvidenceWatchResult(**payload, result_sha256="0" * 64)
    normalized = result.model_dump(mode="json", exclude={"result_sha256"})
    return result.model_copy(update={"result_sha256": content_digest(normalized)})


def parse_metadata_response(request: EvidenceWatchRequest | dict, body: bytes, *, fetched_at: datetime,
                            acquisition_mode: str = "provided_response") -> EvidenceWatchResult:
    """Parse bounded supplied metadata without claiming a live fetch or appraisal."""
    request = EvidenceWatchRequest.model_validate(request)
    if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
        raise ValueError("Acquisition time must be timezone-aware.")
    if acquisition_mode not in {"online", "provided_response"}:
        raise ValueError("Unsupported acquisition mode.")
    if not isinstance(body, bytes):
        raise TypeError("Metadata response must be bytes.")
    digest = hashlib.sha256(body).hexdigest()
    base = dict(fetched_at=fetched_at.astimezone(timezone.utc), source_payload_sha256=digest)
    try:
        if len(body) > MAX_RESPONSE_BYTES:
            raise EvidenceWatchError("response_limit", "Metadata response exceeds the configured byte limit.")
        data = json.loads(body)
        if not isinstance(data, dict) or type(data.get("hitCount")) is not int or data["hitCount"] < 0:
            raise EvidenceWatchError("malformed_response", "Metadata response is missing a valid hitCount.")
        result_list = data.get("resultList")
        if not isinstance(result_list, dict) or not isinstance(result_list.get("result"), list):
            raise EvidenceWatchError("malformed_response", "Metadata response is missing a result list.")
        records = result_list["result"]
        if len(records) > request.max_records or len(records) > data["hitCount"]:
            raise EvidenceWatchError("response_limit", "Returned metadata count exceeds the requested or declared limit.")
        candidates = tuple(_candidate(record) for record in records)
        if len({item.candidate_id for item in candidates}) != len(candidates):
            raise EvidenceWatchError("invalid_record", "Duplicate metadata identifiers require source review.")
        return _result(request, acquisition_mode=acquisition_mode, status="discovered", **base,
                       provider_hit_count=data["hitCount"], provider_api_version=_text(data, "version", maximum=30),
                       candidates=candidates)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValidationError):
        failure = EvidenceWatchError("malformed_response", "Metadata response is not valid supported JSON.")
    except EvidenceWatchError as exc:
        failure = exc
    return _result(request, acquisition_mode=acquisition_mode, status="failed", **base,
                   error_code=failure.code, error_detail=failure.detail)


def discover_sources(request: EvidenceWatchRequest | dict, *, online: bool = False,
                     transport: Callable[[str], bytes] | None = None,
                     now: Callable[[], datetime] | None = None) -> EvidenceWatchResult:
    """Fetch a single metadata page only after an explicit opt-in; never persist."""
    request = EvidenceWatchRequest.model_validate(request)
    if online is not True:
        return _result(request, acquisition_mode="not_requested", status="online_not_requested")
    clock = now or (lambda: datetime.now(timezone.utc))
    try:
        body = (transport or _read_online)(request_url(request))
        return parse_metadata_response(request, body, fetched_at=clock(), acquisition_mode="online")
    except (socket.timeout, TimeoutError):
        failure = EvidenceWatchError("timeout", "The metadata request timed out; no cached success was substituted.")
    except HTTPError as exc:
        failure = EvidenceWatchError("redirect_blocked" if 300 <= exc.code < 400 else "http_error",
                                     f"The metadata provider returned HTTP {exc.code}; no clinical content was updated.")
    except URLError as exc:
        failure = (EvidenceWatchError("timeout", "The metadata request timed out; no cached success was substituted.")
                   if isinstance(exc.reason, (socket.timeout, TimeoutError)) else
                   EvidenceWatchError("network_error", "Metadata provider could not be reached; no cached success was substituted."))
    except OSError:
        failure = EvidenceWatchError("network_error", "Metadata provider could not be reached; no cached success was substituted.")
    except EvidenceWatchError as exc:
        failure = exc
    return _result(request, acquisition_mode="online", status="failed", error_code=failure.code,
                   error_detail=failure.detail)
