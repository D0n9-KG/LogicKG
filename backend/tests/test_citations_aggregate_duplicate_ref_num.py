# backend/tests/test_citations_aggregate_duplicate_ref_num.py
"""
Tests that duplicate ref_num entries are handled safely in build_reference_and_cite_records.

Root cause: dict comprehension `{r.ref_num: r for r in doc.references}` silently drops
duplicate ref_num entries (last wins), causing crossref resolution and citation mapping
to silently fail for the overwritten references.

Fix: Keep first occurrence and emit logger.warning for visibility.
"""
from __future__ import annotations

import logging

from app.citations.aggregate import build_reference_and_cite_records
from app.crossref.client import CrossrefResolveResult
from app.ingest.models import CitationEvent, DocumentIR, MdSpan, PaperDraft, ReferenceEntry


class _FakeCrossref:
    """Minimal Crossref stub that records which raw strings were resolved."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve_reference(self, raw: str) -> CrossrefResolveResult:
        self.calls.append(raw)
        return CrossrefResolveResult(query=raw, topk=[], selected=None, confidence=0.0)

    def dumps(self, result: CrossrefResolveResult) -> str:  # noqa: ARG002
        return "{}"


def _paper() -> PaperDraft:
    return PaperDraft(
        paper_source="paperA",
        md_path="C:/tmp/paperA/source.md",
        title="A",
        title_alt=None,
        authors=[],
        doi="10.1000/papera",
        year=2024,
    )


def _doc_with_duplicate_ref_num() -> DocumentIR:
    paper = _paper()
    return DocumentIR(
        paper=paper,
        chunks=[],
        references=[
            ReferenceEntry(paper_source="paperA", md_path=paper.md_path, ref_num=1, raw="First ref entry"),
            ReferenceEntry(paper_source="paperA", md_path=paper.md_path, ref_num=1, raw="Duplicate of ref 1"),
        ],
        citations=[
            CitationEvent(
                paper_source="paperA",
                md_path=paper.md_path,
                cited_ref_num=1,
                chunk_id="c1",
                span=MdSpan(start_line=10, end_line=12),
                context="cite ref1",
            ),
        ],
    )


def _doc_with_unique_ref_nums() -> DocumentIR:
    paper = _paper()
    return DocumentIR(
        paper=paper,
        chunks=[],
        references=[
            ReferenceEntry(paper_source="paperA", md_path=paper.md_path, ref_num=1, raw="Ref one"),
            ReferenceEntry(paper_source="paperA", md_path=paper.md_path, ref_num=2, raw="Ref two"),
        ],
        citations=[
            CitationEvent(
                paper_source="paperA",
                md_path=paper.md_path,
                cited_ref_num=1,
                chunk_id="c1",
                span=MdSpan(start_line=10, end_line=12),
                context="cite ref1",
            ),
            CitationEvent(
                paper_source="paperA",
                md_path=paper.md_path,
                cited_ref_num=2,
                chunk_id="c2",
                span=MdSpan(start_line=20, end_line=22),
                context="cite ref2",
            ),
        ],
    )


def test_duplicate_ref_num_keeps_first_and_logs_warning(caplog):
    """Duplicate ref_num: only first occurrence is processed; warning is logged."""
    doc = _doc_with_duplicate_ref_num()
    crossref = _FakeCrossref()

    with caplog.at_level(logging.WARNING, logger="app.citations.aggregate"):
        out = build_reference_and_cite_records(doc=doc, crossref=crossref)

    # Only the first occurrence should be in refs_out
    refs = out.get("refs") or []
    assert len(refs) == 1, f"Expected 1 ref (deduped), got {len(refs)}"
    assert refs[0]["ref_num"] == 1
    assert refs[0]["raw"] == "First ref entry", "Must keep first occurrence, not the duplicate"

    # Crossref is only called for the retained first entry
    assert crossref.calls == ["First ref entry"], (
        f"Expected only 'First ref entry' to be resolved, got {crossref.calls}"
    )

    # Citation mapping for ref_num=1 still resolves to the unresolved list (no DOI found)
    unresolved = out.get("cites_unresolved") or []
    assert len(unresolved) == 1
    assert unresolved[0]["ref_nums"] == [1]

    # Warning must be logged about the duplicate
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("Duplicate ref_num 1" in msg for msg in warning_messages), (
        f"Expected duplicate ref_num warning, got: {warning_messages}"
    )
    assert any("keeping first occurrence" in msg for msg in warning_messages)


def test_unique_ref_nums_produce_no_duplicate_warning(caplog):
    """No duplicate ref_nums: all refs processed, no warning logged."""
    doc = _doc_with_unique_ref_nums()
    crossref = _FakeCrossref()

    with caplog.at_level(logging.WARNING, logger="app.citations.aggregate"):
        out = build_reference_and_cite_records(doc=doc, crossref=crossref)

    refs = out.get("refs") or []
    assert len(refs) == 2
    assert [r["ref_num"] for r in refs] == [1, 2]

    # Crossref called once per unique reference
    assert crossref.calls == ["Ref one", "Ref two"]

    # No duplicate warning emitted
    warning_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("Duplicate ref_num" in msg for msg in warning_messages)
