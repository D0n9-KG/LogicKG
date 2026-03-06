"""Tests for multi-evidence coverage metric (P2-18)."""
from __future__ import annotations

import pytest

from app.extraction.orchestrator import _quality_report


_BASE_SCHEMA = {
    "steps": [
        {"id": "Background", "enabled": True},
        {"id": "Method", "enabled": True},
    ],
    "claim_kinds": [{"id": "Definition", "enabled": True}],
    "rules": {
        "phase1_gate_supported_ratio_min": 0.0,
        "phase1_gate_step_coverage_min": 0.0,
        "phase2_gate_critical_slot_coverage_min": 0.0,
    },
}


def _make_claim(claim_id: str, step_type: str, chunk_ids: list[str]) -> dict:
    return {
        "canonical_claim_id": claim_id,
        "text": f"Claim {claim_id}",
        "step_type": step_type,
        "kinds": ["Definition"],
        "confidence": 0.8,
        "origin_chunk_id": chunk_ids[0] if chunk_ids else "",
        "origin_chunk_ids": chunk_ids,
    }


def _make_judgment(claim_id: str, label: str = "supported") -> dict:
    return {
        "canonical_claim_id": claim_id,
        "support_label": label,
        "judge_score": 0.9,
        "reason": "ok",
    }


def test_multi_evidence_all_single_chunk():
    """All claims with single chunk → ratio = 0."""
    claims = [_make_claim("c1", "Background", ["ch1"]), _make_claim("c2", "Method", ["ch2"])]
    judgments = [_make_judgment("c1"), _make_judgment("c2")]
    report = _quality_report(
        claims_merged=claims, validated=claims, judgments=judgments,
        step_order=["Background", "Method"], schema=_BASE_SCHEMA,
        rules=_BASE_SCHEMA["rules"],
    )
    assert report["multi_evidence_count"] == 0
    assert report["multi_evidence_coverage_ratio"] == pytest.approx(0.0)


def test_multi_evidence_all_multi_chunk():
    """All claims with 2+ chunks → ratio = 1.0."""
    claims = [
        _make_claim("c1", "Background", ["ch1", "ch2"]),
        _make_claim("c2", "Method", ["ch3", "ch4", "ch5"]),
    ]
    judgments = [_make_judgment("c1"), _make_judgment("c2")]
    report = _quality_report(
        claims_merged=claims, validated=claims, judgments=judgments,
        step_order=["Background", "Method"], schema=_BASE_SCHEMA,
        rules=_BASE_SCHEMA["rules"],
    )
    assert report["multi_evidence_count"] == 2
    assert report["multi_evidence_coverage_ratio"] == pytest.approx(1.0)


def test_multi_evidence_mixed():
    """Mix of single and multi-chunk claims."""
    claims = [
        _make_claim("c1", "Background", ["ch1", "ch2"]),
        _make_claim("c2", "Method", ["ch3"]),
        _make_claim("c3", "Background", ["ch4", "ch5"]),
    ]
    judgments = [_make_judgment("c1"), _make_judgment("c2"), _make_judgment("c3")]
    report = _quality_report(
        claims_merged=claims, validated=claims, judgments=judgments,
        step_order=["Background", "Method"], schema=_BASE_SCHEMA,
        rules=_BASE_SCHEMA["rules"],
    )
    assert report["multi_evidence_count"] == 2
    assert report["multi_evidence_coverage_ratio"] == pytest.approx(2.0 / 3.0)


def test_multi_evidence_empty_claims():
    """No claims → ratio = 0, count = 0."""
    report = _quality_report(
        claims_merged=[], validated=[], judgments=[],
        step_order=["Background", "Method"], schema=_BASE_SCHEMA,
        rules=_BASE_SCHEMA["rules"],
    )
    assert report["multi_evidence_count"] == 0
    assert report["multi_evidence_coverage_ratio"] == pytest.approx(0.0)


def test_multi_evidence_no_origin_chunk_ids_field():
    """Claims without origin_chunk_ids field → treated as 0 chunks."""
    claims = [{"canonical_claim_id": "c1", "text": "X", "step_type": "Background",
               "kinds": ["Definition"], "confidence": 0.8}]
    judgments = [_make_judgment("c1")]
    report = _quality_report(
        claims_merged=claims, validated=claims, judgments=judgments,
        step_order=["Background", "Method"], schema=_BASE_SCHEMA,
        rules=_BASE_SCHEMA["rules"],
    )
    assert report["multi_evidence_count"] == 0
    assert report["multi_evidence_coverage_ratio"] == pytest.approx(0.0)
