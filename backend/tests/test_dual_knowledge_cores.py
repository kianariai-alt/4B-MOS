"""Synthetic-only tests: governance, deterministic provenance, and no recommendations."""

from datetime import date
from types import SimpleNamespace

import pytest

from backend.app.services.dual_knowledge_cores import (
    CORE_PACKS,
    build_dual_manifest,
    build_pack_manifest,
)


def _fact(name, domain="orthopedics_knee", *, status="approved", digest="a" * 64):
    return SimpleNamespace(
        id="id-" + name,
        fact_key=name,
        version=1,
        content_sha256=digest,
        clinical_domain=domain,
        status=status,
    )


def _packs(orthopedic=(), xray=(), mri=()):
    return [
        build_pack_manifest(core=core, pack_key=key, clinical_domain=domain, facts=items)
        for (core, key, domain), items in zip(CORE_PACKS, (orthopedic, xray, mri))
    ]


def test_empty_manifest_is_not_clinically_validated():
    result = build_dual_manifest(as_of=date(2026, 10, 19), packs=_packs())
    assert [p.readiness for p in result.packs] == ["empty"] * 3
    assert result.is_diagnosis is False
    assert result.is_recommendation is False
    assert result.is_clinical_clearance is False
    assert result.requires_independent_review is True
    assert all(p.is_clinically_validated is False for p in result.packs)
    assert len(result.combined_manifest_sha256) == 64


def test_approved_pack_deterministically_lists_verified_references_only():
    facts = [_fact("Z"), _fact("A")]
    first = _packs(orthopedic=facts)[0]
    second = _packs(orthopedic=reversed(facts))[0]
    assert first == second
    assert first.approved_fact_count == 2
    assert [f.fact_key for f in first.facts] == ["A", "Z"]
    assert first.readiness == "references_available"
    assert first.is_clinically_validated is False


def test_draft_and_wrong_domain_and_duplicates_are_rejected():
    for items in (
        [_fact("a", status="draft")],
        [_fact("a", domain="imaging_knee_xray")],
        [_fact("a"), _fact("a")],
    ):
        with pytest.raises(ValueError):
            _packs(orthopedic=items)


def test_no_cross_domain_leakage_and_hash_tracks_changes():
    baseline = build_dual_manifest(as_of=date(2026, 10, 19), packs=_packs())
    updated = build_dual_manifest(
        as_of=date(2026, 10, 19),
        packs=_packs(xray=[_fact("x", "imaging_knee_xray")]),
    )
    assert updated.packs[0] == baseline.packs[0]
    assert updated.packs[1].approved_fact_count == 1
    assert updated.combined_manifest_sha256 != baseline.combined_manifest_sha256


def test_manifest_rejects_missing_or_reordered_packs():
    packs = _packs()
    with pytest.raises(ValueError):
        build_dual_manifest(as_of=date.today(), packs=packs[1:])
    with pytest.raises(ValueError):
        build_dual_manifest(as_of=date.today(), packs=list(reversed(packs)))


def test_invalid_sha_rejected():
    with pytest.raises(ValueError):
        _packs(orthopedic=[_fact("invalid", digest="not-a-sha")])
