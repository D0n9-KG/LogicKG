"""Tests for Phase 1.1: Chunk Claim batch extraction + tiered fallback."""
from __future__ import annotations

import pytest
from app.ingest.models import Chunk, DocumentIR, MdSpan, PaperDraft


def _make_doc(n_chunks: int = 6) -> DocumentIR:
    paper = PaperDraft(
        paper_source="batch_test",
        md_path="/tmp/batch_test.md",
        title="Batch Test Paper",
        title_alt=None,
        authors=[],
        doi=None,
        year=None,
    )
    chunks = [
        Chunk(
            chunk_id=f"c{i}",
            paper_source="batch_test",
            md_path="/tmp/batch_test.md",
            span=MdSpan(start_line=i * 10, end_line=i * 10 + 9),
            section=None,
            kind="body",
            text=f"The DEM simulation uses particle radius {i}.0 mm with friction coefficient 0.{i}5.",
        )
        for i in range(n_chunks)
    ]
    return DocumentIR(paper=paper, chunks=chunks, references=[], citations=[])


class TestBatchExtraction:
    """Test _extract_claims_from_chunks_batch_llm and its integration."""

    def test_batch_returns_per_chunk_results(self, monkeypatch):
        """Batch function returns results keyed by chunk_id."""
        from app.extraction import orchestrator

        def _mock_batch(**kwargs):
            chunks = kwargs.get("chunks") or []
            results = {}
            for c in chunks:
                cid = c["chunk_id"]
                text = c["text"]
                results[cid] = [{
                    "text": f"Claim from {cid}",
                    "evidence_quote": text[:40],
                    "step_type": "Method",
                    "kinds": ["Observation"],
                    "confidence": 0.8,
                    "span_start": 0,
                    "span_end": 40,
                    "match_mode": "exact",
                }]
            return {
                "results": results,
                "failed_chunk_ids": [],
                "quote_mismatch_count": 0,
                "unknown_chunk_id_count": 0,
            }

        monkeypatch.setattr(orchestrator, "_extract_claims_from_chunks_batch_llm", _mock_batch)

        doc = _make_doc(6)
        result = orchestrator._default_claim_extractor(
            doc=doc,
            paper_id="p1",
            schema={"rules": {"phase1_claim_batch_size": 6}, "prompts": {}},
            step_order=["Method"],
            logic={},
        )
        assert result["chunk_total"] == 6
        assert result["chunk_fail_count"] == 0
        assert len(result["candidates"]) == 6
        # All candidates should have distinct origin_chunk_ids
        origin_ids = {c["origin_chunk_id"] for c in result["candidates"]}
        assert len(origin_ids) == 6

    def test_tiered_fallback_on_batch_failure(self, monkeypatch):
        """When batch fails, falls back to single-chunk extraction."""
        from app.extraction import orchestrator

        def _batch_fail(**kwargs):
            chunks = kwargs.get("chunks") or []
            return {
                "results": {},
                "failed_chunk_ids": [c["chunk_id"] for c in chunks],
                "quote_mismatch_count": 0,
                "unknown_chunk_id_count": 0,
            }

        single_calls = []

        def _single_ok(**kwargs):
            single_calls.append(kwargs.get("chunk_text", "")[:20])
            return [{
                "text": "Single claim",
                "evidence_quote": kwargs["chunk_text"][:30],
                "step_type": "Method",
                "kinds": [],
                "confidence": 0.7,
                "span_start": 0,
                "span_end": 30,
                "match_mode": "exact",
            }]

        monkeypatch.setattr(orchestrator, "_extract_claims_from_chunks_batch_llm", _batch_fail)
        monkeypatch.setattr(orchestrator, "_extract_claims_from_chunk_llm", _single_ok)

        doc = _make_doc(3)
        result = orchestrator._default_claim_extractor(
            doc=doc,
            paper_id="p1",
            schema={"rules": {"phase1_claim_batch_size": 3}, "prompts": {}},
            step_order=["Method"],
            logic={},
        )
        # All 3 chunks should have been processed via single fallback
        assert len(result["candidates"]) == 3
        assert len(single_calls) == 3

    def test_batch_stats_in_result(self, monkeypatch):
        """Result includes chunk_extraction_stats with batch metrics."""
        from app.extraction import orchestrator

        def _mock_batch(**kwargs):
            chunks = kwargs.get("chunks") or []
            return {
                "results": {c["chunk_id"]: [] for c in chunks},
                "failed_chunk_ids": [],
                "quote_mismatch_count": 2,
                "unknown_chunk_id_count": 1,
            }

        monkeypatch.setattr(orchestrator, "_extract_claims_from_chunks_batch_llm", _mock_batch)

        doc = _make_doc(4)
        result = orchestrator._default_claim_extractor(
            doc=doc,
            paper_id="p1",
            schema={"rules": {"phase1_claim_batch_size": 4}, "prompts": {}},
            step_order=["Method"],
            logic={},
        )
        stats = result.get("chunk_extraction_stats")
        assert stats is not None
        assert stats["batch_size"] == 4
        assert stats["batch_quote_mismatch_count"] == 2
        assert stats["batch_unknown_chunk_id_count"] == 1

    def test_batch_size_configurable(self, monkeypatch):
        """phase1_claim_batch_size controls how many chunks per batch."""
        from app.extraction import orchestrator

        batch_sizes_seen = []

        def _mock_batch(**kwargs):
            chunks = kwargs.get("chunks") or []
            batch_sizes_seen.append(len(chunks))
            return {
                "results": {c["chunk_id"]: [] for c in chunks},
                "failed_chunk_ids": [],
                "quote_mismatch_count": 0,
                "unknown_chunk_id_count": 0,
            }

        monkeypatch.setattr(orchestrator, "_extract_claims_from_chunks_batch_llm", _mock_batch)

        doc = _make_doc(5)
        orchestrator._default_claim_extractor(
            doc=doc,
            paper_id="p1",
            schema={"rules": {"phase1_claim_batch_size": 2}, "prompts": {}},
            step_order=["Method"],
            logic={},
        )
        # 5 chunks / batch_size=2 → 3 batches (2, 2, 1)
        assert len(batch_sizes_seen) == 3
        assert batch_sizes_seen == [2, 2, 1]


class TestValidateBatchClaims:
    """Test _validate_batch_claims_for_chunk."""

    def test_valid_claims_pass(self):
        from app.extraction.orchestrator import _validate_batch_claims_for_chunk

        chunk_text = "The DEM simulation uses particle radius 2.0 mm."
        raw = [{
            "text": "DEM uses 2.0mm radius",
            "evidence_quote": "particle radius 2.0 mm",
            "step_type": "Method",
            "claim_kinds": ["Observation"],
            "confidence": 0.9,
        }]
        valid, mismatches = _validate_batch_claims_for_chunk(
            raw_claims=raw,
            chunk_text=chunk_text,
            step_set={"Method", "Background"},
            kind_set={"Observation", "Definition"},
            max_claims=5,
        )
        assert len(valid) == 1
        assert mismatches == 0

    def test_quote_mismatch_counted(self):
        from app.extraction.orchestrator import _validate_batch_claims_for_chunk

        chunk_text = "The DEM simulation uses particle radius 2.0 mm."
        raw = [{
            "text": "Some claim",
            "evidence_quote": "this quote does not exist in chunk",
            "step_type": "Method",
            "claim_kinds": [],
            "confidence": 0.5,
        }]
        valid, mismatches = _validate_batch_claims_for_chunk(
            raw_claims=raw,
            chunk_text=chunk_text,
            step_set={"Method"},
            kind_set=set(),
            max_claims=5,
        )
        assert len(valid) == 0
        assert mismatches == 1
