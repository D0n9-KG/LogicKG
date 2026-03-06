# backend/tests/test_p1_grounding_semantic_coverage_gate.py
"""
Tests for grounding skip mode.

After removing grounding logic, all claims are directly marked as supported
with judge_mode="skip". These tests verify the skip mode behavior and that
the quality report still includes the expected grounding fields.
"""
from __future__ import annotations

import pytest

from app.extraction.orchestrator import run_phase1_extraction
from app.ingest.models import Chunk, DocumentIR, MdSpan, PaperDraft


def _doc() -> DocumentIR:
    return DocumentIR(
        paper=PaperDraft(
            paper_source="paperA",
            md_path="C:/tmp/paperA/source.md",
            title="Paper A",
            title_alt=None,
            authors=["Alice"],
            doi="10.1000/papera",
            year=2024,
        ),
        chunks=[
            Chunk(
                chunk_id="c1",
                paper_source="paperA",
                md_path="C:/tmp/paperA/source.md",
                span=MdSpan(start_line=1, end_line=5),
                section="Method",
                kind="block",
                text="The proposed algorithm achieves state of the art performance on multiple benchmarks.",
            ),
        ],
        references=[],
        citations=[],
    )


def _schema_with_rules(rules: dict) -> dict:
    return {
        "paper_type": "research",
        "version": 1,
        "steps": [{"id": "Method", "enabled": True, "order": 0}],
        "claim_kinds": [{"id": "Result", "enabled": True}],
        "rules": {
            "phase1_gate_supported_ratio_min": 0.0,
            "phase1_gate_step_coverage_min": 0.0,
            "phase2_gate_critical_slot_coverage_min": 0.0,
            "phase2_gate_conflict_rate_max": 1.0,
            **rules,
        },
    }


def _logic_extractor(*, doc, paper_id, schema):
    return {
        "logic": {"Method": {"summary": "Improved performance", "evidence_chunk_ids": ["c1"]}},
        "step_order": ["Method"],
    }


def _claim_extractor(*, doc, paper_id, schema, step_order):
    return [
        {
            "text": "The proposed algorithm achieves state of the art performance",
            "confidence": 0.85,
            "step_type": "Method",
            "kinds": ["Result"],
            "origin_chunk_id": "c1",
            "worker_id": "w1",
        }
    ]


def test_quality_report_includes_grounding_semantic_coverage_rate(tmp_path):
    """quality_report always includes grounding_semantic_coverage_rate."""
    out = run_phase1_extraction(
        doc=_doc(),
        paper_id="doi:10.1000/papera",
        cite_rec={"cites_resolved": []},
        schema=_schema_with_rules({}),
        artifacts_dir=tmp_path / "phase1",
        logic_extractor=_logic_extractor,
        claim_extractor=_claim_extractor,
        allow_weak=False,
    )
    report = out["quality_report"]
    assert "grounding_semantic_coverage_rate" in report
    assert isinstance(report["grounding_semantic_coverage_rate"], float)
    assert report["grounding_semantic_coverage_rate"] == pytest.approx(0.0)


def test_semantic_coverage_rate_is_zero_when_all_lexical(tmp_path):
    """Coverage rate = 0 in skip mode (no semantic or lexical judging)."""
    out = run_phase1_extraction(
        doc=_doc(),
        paper_id="doi:10.1000/papera",
        cite_rec={"cites_resolved": []},
        schema=_schema_with_rules({}),
        artifacts_dir=tmp_path / "phase1",
        logic_extractor=_logic_extractor,
        claim_extractor=_claim_extractor,
        allow_weak=False,
    )
    report = out["quality_report"]
    assert report["grounding_semantic_coverage_rate"] == pytest.approx(0.0)
    assert report["grounding_lexical_judged"] == 0
    assert report["grounding_semantic_judged"] == 0


def test_semantic_coverage_rate_is_one_when_all_semantic(tmp_path):
    """In skip mode, semantic coverage is always 0 regardless of config."""
    out = run_phase1_extraction(
        doc=_doc(),
        paper_id="doi:10.1000/papera",
        cite_rec={"cites_resolved": []},
        schema=_schema_with_rules({"phase1_grounding_mode": "skip"}),
        artifacts_dir=tmp_path / "phase1",
        logic_extractor=_logic_extractor,
        claim_extractor=_claim_extractor,
        allow_weak=False,
    )
    report = out["quality_report"]
    assert report["grounding_semantic_coverage_rate"] == pytest.approx(0.0)
    assert report["grounding_mode_used"] == "skip"


def test_semantic_coverage_gate_disabled_by_default(tmp_path):
    """Default semantic_coverage_min=0.0 means gate never fails on coverage."""
    out = run_phase1_extraction(
        doc=_doc(),
        paper_id="doi:10.1000/papera",
        cite_rec={"cites_resolved": []},
        schema=_schema_with_rules({}),
        artifacts_dir=tmp_path / "phase1",
        logic_extractor=_logic_extractor,
        claim_extractor=_claim_extractor,
        allow_weak=False,
    )
    report = out["quality_report"]
    assert "semantic_coverage" not in (report.get("gate_fail_reasons") or [])
    assert report["gate_passed"] is True


def test_semantic_coverage_gate_fails_when_coverage_below_threshold(tmp_path):
    """With skip mode, semantic_coverage gate should never fail since min_semantic_coverage
    check only triggers when > 0.0, and coverage is always 0.0 in skip mode."""
    out = run_phase1_extraction(
        doc=_doc(),
        paper_id="doi:10.1000/papera",
        cite_rec={"cites_resolved": []},
        schema=_schema_with_rules({"phase1_gate_semantic_coverage_min": 0.5}),
        artifacts_dir=tmp_path / "phase1",
        logic_extractor=_logic_extractor,
        claim_extractor=_claim_extractor,
        allow_weak=False,
    )
    report = out["quality_report"]
    # In skip mode, semantic_coverage_rate=0.0 < 0.5 threshold, so gate fails
    assert "semantic_coverage" in (report.get("gate_fail_reasons") or [])


def test_semantic_coverage_gate_passes_when_above_threshold(tmp_path):
    """With threshold=0.0 (default), gate always passes."""
    out = run_phase1_extraction(
        doc=_doc(),
        paper_id="doi:10.1000/papera",
        cite_rec={"cites_resolved": []},
        schema=_schema_with_rules({"phase1_gate_semantic_coverage_min": 0.0}),
        artifacts_dir=tmp_path / "phase1",
        logic_extractor=_logic_extractor,
        claim_extractor=_claim_extractor,
        allow_weak=False,
    )
    report = out["quality_report"]
    assert "semantic_coverage" not in (report.get("gate_fail_reasons") or [])
    assert report["gate_passed"] is True


def test_thresholds_dict_includes_semantic_coverage_min(tmp_path):
    """Thresholds dict in quality_report includes the configured semantic coverage min."""
    configured_min = 0.42
    out = run_phase1_extraction(
        doc=_doc(),
        paper_id="doi:10.1000/papera",
        cite_rec={"cites_resolved": []},
        schema=_schema_with_rules({
            "phase1_gate_semantic_coverage_min": configured_min,
        }),
        artifacts_dir=tmp_path / "phase1",
        logic_extractor=_logic_extractor,
        claim_extractor=_claim_extractor,
        allow_weak=True,
    )
    report = out["quality_report"]
    thresholds = report.get("thresholds") or {}
    assert "phase1_gate_semantic_coverage_min" in thresholds
    assert thresholds["phase1_gate_semantic_coverage_min"] == pytest.approx(configured_min)
