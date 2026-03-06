from __future__ import annotations

import pytest
from app.ingest.models import Chunk, DocumentIR, MdSpan, PaperDraft


def _make_doc(n_chunks: int = 4) -> DocumentIR:
    paper = PaperDraft(
        paper_source="test_paper",
        md_path="/tmp/test.md",
        title="Test Paper",
        title_alt=None,
        authors=[],
        doi=None,
        year=None,
    )
    chunks = [
        Chunk(
            chunk_id=f"c{i}",
            paper_source="test_paper",
            md_path="/tmp/test.md",
            span=MdSpan(start_line=i, end_line=i + 1),
            section=None,
            kind="body",
            text=f"Chunk text number {i} contains scientific content.",
        )
        for i in range(n_chunks)
    ]
    return DocumentIR(paper=paper, chunks=chunks, references=[], citations=[])


# ---------------------------------------------------------------------------
# Task 1: chunk fail count tests
# ---------------------------------------------------------------------------

def test_chunk_fail_count_recorded_in_result(monkeypatch):
    """When LLM throws for even-indexed chunks, chunk_fail_count equals those failures."""
    from app.extraction import orchestrator

    call_count = 0

    def _failing_extract(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count % 2 == 0:
            raise RuntimeError("injected LLM failure")
        return [{"text": "result", "step_type": "Method", "kinds": [], "confidence": 0.8}]

    # Force batch extraction to fail so all chunks fall back to single-chunk path
    def _batch_always_fail(**kwargs):
        chunks = kwargs.get("chunks") or []
        return {
            "results": {},
            "failed_chunk_ids": [c["chunk_id"] for c in chunks],
            "quote_mismatch_count": 0,
            "unknown_chunk_id_count": 0,
        }

    monkeypatch.setattr(orchestrator, "_extract_claims_from_chunk_llm", _failing_extract)
    monkeypatch.setattr(orchestrator, "_extract_claims_from_chunks_batch_llm", _batch_always_fail)

    doc = _make_doc(n_chunks=4)
    result = orchestrator._default_claim_extractor(
        doc=doc,
        paper_id="p1",
        schema={"rules": {}, "prompts": {}},
        step_order=["Method"],
        logic={},
    )

    assert isinstance(result, dict), "return type must be dict"
    assert "candidates" in result, "result must have 'candidates'"
    assert "chunk_fail_count" in result, "result must have 'chunk_fail_count'"
    assert "chunk_total" in result, "result must have 'chunk_total'"
    # 4 chunks, 2 fail (call 2 and 4)
    assert result["chunk_fail_count"] == 2
    assert result["chunk_total"] == 4
    assert len(result["candidates"]) == 2


def test_chunk_fail_count_zero_on_success(monkeypatch):
    """When all chunks succeed, chunk_fail_count is 0."""
    from app.extraction import orchestrator

    def _ok_extract(**kwargs):
        return [{"text": "some result", "step_type": "Method", "kinds": [], "confidence": 0.8}]

    # Force batch to fail so single-chunk path is used
    def _batch_always_fail(**kwargs):
        chunks = kwargs.get("chunks") or []
        return {
            "results": {},
            "failed_chunk_ids": [c["chunk_id"] for c in chunks],
            "quote_mismatch_count": 0,
            "unknown_chunk_id_count": 0,
        }

    monkeypatch.setattr(orchestrator, "_extract_claims_from_chunk_llm", _ok_extract)
    monkeypatch.setattr(orchestrator, "_extract_claims_from_chunks_batch_llm", _batch_always_fail)

    doc = _make_doc(n_chunks=3)
    result = orchestrator._default_claim_extractor(
        doc=doc,
        paper_id="p1",
        schema={"rules": {}, "prompts": {}},
        step_order=["Method"],
        logic={},
    )
    assert result["chunk_fail_count"] == 0
    assert result["chunk_total"] == 3


# ---------------------------------------------------------------------------
# Task 4: sentence boundary truncation tests
# ---------------------------------------------------------------------------

def test_truncate_to_sentence_boundary_basic():
    """Truncated text ends at a sentence boundary."""
    from app.extraction.orchestrator import _truncate_to_sentence_boundary

    text = "First sentence here. Second sentence follows. Third one ends."
    result = _truncate_to_sentence_boundary(text, max_chars=45)
    assert result.endswith(".")
    assert len(result) <= 45


def test_truncate_short_text_unchanged():
    """Short text within max_chars is returned unchanged."""
    from app.extraction.orchestrator import _truncate_to_sentence_boundary

    text = "Short text."
    result = _truncate_to_sentence_boundary(text, max_chars=1000)
    assert result == text


def test_truncate_no_sentence_boundary_falls_back():
    """When no sentence boundary exists in window, hard-truncate at max_chars."""
    from app.extraction.orchestrator import _truncate_to_sentence_boundary

    text = "a" * 200
    result = _truncate_to_sentence_boundary(text, max_chars=50)
    assert len(result) <= 50


def test_truncate_chinese_punctuation():
    """Chinese sentence-ending punctuation (。) is also treated as a boundary."""
    from app.extraction.orchestrator import _truncate_to_sentence_boundary

    text = "这是第一句话。这是第二句话，包含更多内容。这是第三句话结尾。"
    # max_chars=10: window "这是第一句话。这是第", half=5, "。" at pos 6 > 5 → truncates at boundary
    result = _truncate_to_sentence_boundary(text, max_chars=10)
    assert result.endswith("。")
    assert len(result) <= 10


# ---------------------------------------------------------------------------
# Task 6: claim span validation tests
# ---------------------------------------------------------------------------

def test_validate_claim_span_valid():
    """Valid span within chunk bounds is returned unchanged."""
    from app.extraction.orchestrator import _validate_claim_span

    chunk = "Alpha runs faster. Beta method outperforms baseline."
    assert _validate_claim_span(chunk, 0, 18) == (0, 18)


def test_validate_claim_span_out_of_bounds():
    """Out-of-bounds end index returns (-1, -1)."""
    from app.extraction.orchestrator import _validate_claim_span

    chunk = "Alpha runs faster. Beta method outperforms baseline."
    assert _validate_claim_span(chunk, 0, 9999) == (-1, -1)


def test_validate_claim_span_reversed():
    """Reversed span (start > end) returns (-1, -1)."""
    from app.extraction.orchestrator import _validate_claim_span

    chunk = "Alpha runs faster."
    assert _validate_claim_span(chunk, 18, 0) == (-1, -1)


def test_validate_claim_span_non_integer():
    """Non-integer inputs return (-1, -1)."""
    from app.extraction.orchestrator import _validate_claim_span

    chunk = "Some text."
    assert _validate_claim_span(chunk, None, None) == (-1, -1)
    assert _validate_claim_span(chunk, "abc", "def") == (-1, -1)
