from __future__ import annotations

import threading
import time

from app.citations.aggregate import build_reference_and_cite_records
from app.crossref.client import CrossrefResolveResult
from app.ingest.models import CitationEvent, DocumentIR, MdSpan, PaperDraft, ReferenceEntry


class _ParallelCrossref:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def recommended_workers(self) -> int:
        return 2

    def resolve_reference(self, raw: str) -> CrossrefResolveResult:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self._lock:
            self.active -= 1
        return CrossrefResolveResult(query=raw, topk=[], selected=None, confidence=0.0)

    def dumps(self, result: CrossrefResolveResult) -> str:  # noqa: ARG002
        return "{}"


def _doc() -> DocumentIR:
    paper = PaperDraft(
        paper_source="paperA",
        md_path="C:/tmp/paperA/source.md",
        title="A",
        title_alt=None,
        authors=[],
        doi="10.1000/papera",
        year=2024,
    )
    references = [
        ReferenceEntry(paper_source="paperA", md_path=paper.md_path, ref_num=1, raw="Ref One"),
        ReferenceEntry(paper_source="paperA", md_path=paper.md_path, ref_num=2, raw="Ref Two"),
        ReferenceEntry(paper_source="paperA", md_path=paper.md_path, ref_num=3, raw="Ref Three"),
        ReferenceEntry(paper_source="paperA", md_path=paper.md_path, ref_num=4, raw="Ref Four"),
    ]
    citations = [
        CitationEvent(
            paper_source="paperA",
            md_path=paper.md_path,
            cited_ref_num=idx,
            chunk_id=f"c{idx}",
            span=MdSpan(start_line=idx * 10, end_line=idx * 10 + 1),
            context=f"cite ref{idx}",
        )
        for idx in range(1, 5)
    ]
    return DocumentIR(paper=paper, chunks=[], references=references, citations=citations)


def test_build_reference_and_cite_records_uses_bounded_parallel_resolution() -> None:
    crossref = _ParallelCrossref()

    out = build_reference_and_cite_records(doc=_doc(), crossref=crossref)

    assert len(out.get("refs") or []) == 4
    assert crossref.max_active >= 2
