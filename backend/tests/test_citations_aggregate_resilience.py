from __future__ import annotations

import unittest
from unittest.mock import Mock

from app.citations.aggregate import build_reference_and_cite_records
from app.crossref.client import CrossrefResolveResult, CrossrefWork
from app.ingest.models import CitationEvent, DocumentIR, MdSpan, PaperDraft, ReferenceEntry


class CitationAggregateResilienceTests(unittest.TestCase):
    def _doc(self) -> DocumentIR:
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
        ]
        citations = [
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
                span=MdSpan(start_line=20, end_line=21),
                context="cite ref2",
            ),
        ]
        return DocumentIR(paper=paper, chunks=[], references=references, citations=citations)

    def test_crossref_error_on_one_reference_does_not_abort_whole_doc(self) -> None:
        doc = self._doc()
        ok = CrossrefWork(
            doi="10.2000/ref2",
            title="Ref Two",
            year=2020,
            venue="J",
            authors=["Alice"],
            score=80.0,
        )
        crossref = Mock()
        crossref.resolve_reference.side_effect = [
            RuntimeError("429 Too Many Requests"),
            CrossrefResolveResult(query="Ref Two", topk=[ok], selected=ok, confidence=0.8),
        ]
        crossref.dumps.side_effect = lambda x: "{}"

        out = build_reference_and_cite_records(doc=doc, crossref=crossref)

        self.assertEqual(len(out.get("refs") or []), 2)
        refs = {int(r["ref_num"]): r for r in (out.get("refs") or [])}
        self.assertIn("crossref_error", refs[1])
        self.assertTrue(str(refs[1].get("crossref_error") or "").startswith("429"))
        self.assertEqual(refs[2].get("resolved_doi"), "10.2000/ref2")
        self.assertEqual(len(out.get("cites_resolved") or []), 1)
        self.assertEqual(len(out.get("cites_unresolved") or []), 1)


if __name__ == "__main__":
    unittest.main()

