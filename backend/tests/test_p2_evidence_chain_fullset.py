# backend/tests/test_p2_evidence_chain_fullset.py
"""
Tests for P2 Fix: evidence_chunk_ids now uses all origin_chunk_ids (full evidence chain).

Previously: evidence_chunk_ids = [origin_chunk_id]  # only first chunk
Fix:        evidence_chunk_ids = origin_chunk_ids    # all accumulated chunks
"""
from __future__ import annotations

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
                text="Method chunk text",
            ),
            Chunk(
                chunk_id="c2",
                paper_source="paperA",
                md_path="C:/tmp/paperA/source.md",
                span=MdSpan(start_line=6, end_line=10),
                section="Result",
                kind="block",
                text="Result chunk text",
            ),
        ],
        references=[],
        citations=[],
    )


def _schema() -> dict:
    return {
        "paper_type": "research",
        "version": 1,
        "steps": [
            {"id": "Method", "enabled": True, "order": 0},
            {"id": "Result", "enabled": True, "order": 1},
        ],
        "claim_kinds": [{"id": "Result", "enabled": True}],
        "rules": {
            "phase1_gate_supported_ratio_min": 0.0,
            "phase1_gate_step_coverage_min": 0.0,
            "phase2_gate_critical_slot_coverage_min": 0.0,
            "phase2_gate_conflict_rate_max": 1.0,
        },
    }


def _logic_extractor(*, doc, paper_id, schema):
    return {
        "logic": {
            "Method": {"summary": "Method summary", "evidence_chunk_ids": ["c1"]},
            "Result": {"summary": "Result summary", "evidence_chunk_ids": ["c2"]},
        },
        "step_order": ["Method", "Result"],
    }


def test_single_origin_chunk_preserved_in_evidence():
    """Single origin_chunk_id is still preserved in evidence_chunk_ids."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        def _claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "Method improves performance",
                    "confidence": 0.9,
                    "step_type": "Method",
                    "kinds": ["Result"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                }
            ]

        out = run_phase1_extraction(
            doc=_doc(),
            paper_id="doi:10.1000/papera",
            cite_rec={"cites_resolved": []},
            schema=_schema(),
            artifacts_dir=Path(tmpdir) / "phase1",
            logic_extractor=_logic_extractor,
            claim_extractor=_claim_extractor,

            allow_weak=False,
        )

    validated = out["validated_claims"]
    assert len(validated) == 1
    claim = validated[0]
    assert "c1" in claim["evidence_chunk_ids"]


def test_multiple_origin_chunks_all_in_evidence(tmp_path):
    """When claim has multiple origin_chunk_ids, all appear in evidence_chunk_ids."""

    same_text = "The proposed approach achieves superior results"

    def _claim_extractor(*, doc, paper_id, schema, step_order):
        # Same claim text mentioned in two chunks (two workers found it)
        return [
            {
                "text": same_text,
                "confidence": 0.9,
                "step_type": "Method",
                "kinds": ["Result"],
                "origin_chunk_id": "c1",
                "worker_id": "w1",
            },
            {
                "text": same_text,
                "confidence": 0.85,
                "step_type": "Method",
                "kinds": ["Result"],
                "origin_chunk_id": "c2",  # Different chunk
                "worker_id": "w2",
            },
        ]

    out = run_phase1_extraction(
        doc=_doc(),
        paper_id="doi:10.1000/papera",
        cite_rec={"cites_resolved": []},
        schema=_schema(),
        artifacts_dir=tmp_path / "phase1",
        logic_extractor=_logic_extractor,
        claim_extractor=_claim_extractor,

        allow_weak=False,
    )

    validated = out["validated_claims"]
    assert len(validated) == 1
    claim = validated[0]

    # Both chunks should appear in evidence_chunk_ids (not just the first)
    evidence_ids = claim["evidence_chunk_ids"]
    assert "c1" in evidence_ids, f"c1 missing from evidence_chunk_ids: {evidence_ids}"
    assert "c2" in evidence_ids, f"c2 missing from evidence_chunk_ids: {evidence_ids}"


def test_cross_step_collision_evidence_merged_in_final_output(tmp_path):
    """Cross-step merge result: evidence from both steps appears in final claim."""

    same_text = "Results are significantly better than baseline"

    def _claim_extractor(*, doc, paper_id, schema, step_order):
        return [
            {
                "text": same_text,
                "confidence": 0.8,
                "step_type": "Method",
                "kinds": ["Result"],
                "origin_chunk_id": "c1",
                "worker_id": "w1",
            },
            {
                "text": same_text,
                "confidence": 0.9,
                "step_type": "Result",
                "kinds": ["Result"],
                "origin_chunk_id": "c2",  # Different step, different chunk
                "worker_id": "w2",
            },
        ]

    out = run_phase1_extraction(
        doc=_doc(),
        paper_id="doi:10.1000/papera",
        cite_rec={"cites_resolved": []},
        schema=_schema(),
        artifacts_dir=tmp_path / "phase1",
        logic_extractor=_logic_extractor,
        claim_extractor=_claim_extractor,

        allow_weak=False,
    )

    validated = out["validated_claims"]
    # After cross-step dedup, only 1 claim (Method step wins, rank 0 < rank 1)
    assert len(validated) == 1
    claim = validated[0]

    # Evidence from both steps should be in the output
    evidence_ids = claim["evidence_chunk_ids"]
    assert "c1" in evidence_ids, "c1 (Method evidence) missing"
    assert "c2" in evidence_ids, "c2 (Result evidence merged from discarded step) missing"
