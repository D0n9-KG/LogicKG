from __future__ import annotations

import unittest

from app.citations.citation_event_recovery import recover_citation_events_from_references
from app.ingest.models import Chunk, CitationEvent, DocumentIR, MdSpan, PaperDraft, ReferenceEntry


def _paper() -> PaperDraft:
    return PaperDraft(
        paper_source="paperA",
        md_path="C:/tmp/paperA/paper.md",
        title="A",
        title_alt=None,
        authors=[],
        doi=None,
        year=2024,
    )


def _chunk(chunk_id: str, text: str, start: int, end: int) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        paper_source="paperA",
        md_path="C:/tmp/paperA/paper.md",
        span=MdSpan(start_line=start, end_line=end),
        section="Method",
        kind="block",
        text=text,
    )


class CitationEventRecoveryTests(unittest.TestCase):
    def test_recovers_author_year_citations_when_events_missing(self) -> None:
        doc = DocumentIR(
            paper=_paper(),
            chunks=[
                _chunk(
                    "c1",
                    "The method follows prior work (Belheine et al., 2009) and extends it.",
                    10,
                    12,
                )
            ],
            references=[
                ReferenceEntry(
                    paper_source="paperA",
                    md_path="C:/tmp/paperA/paper.md",
                    ref_num=1,
                    raw="Belheine, N., Plassiard, J.P., Donze, F.V. (2009). Numerical simulation ...",
                )
            ],
            citations=[],
        )
        recovered, report = recover_citation_events_from_references(
            doc,
            rules={
                "citation_event_recovery_enabled": True,
                "citation_event_recovery_trigger_max_existing_events": 0,
                "citation_event_recovery_numeric_bracket_enabled": False,
                "citation_event_recovery_author_year_enabled": True,
            },
        )
        self.assertEqual(report.get("status"), "recovered")
        self.assertEqual(report.get("recovered_events"), 1)
        self.assertEqual(len(recovered.citations), 1)
        self.assertEqual(int(recovered.citations[0].cited_ref_num), 1)

    def test_skips_when_existing_events_above_dynamic_threshold(self) -> None:
        paper = _paper()
        existing = CitationEvent(
            paper_source=paper.paper_source,
            md_path=paper.md_path,
            cited_ref_num=1,
            chunk_id="c1",
            span=MdSpan(start_line=3, end_line=3),
            context="existing",
        )
        doc = DocumentIR(
            paper=paper,
            chunks=[_chunk("c1", "[1] baseline", 3, 3)],
            references=[ReferenceEntry(paper_source=paper.paper_source, md_path=paper.md_path, ref_num=1, raw="Ref 2001.")],
            citations=[existing],
        )
        recovered, report = recover_citation_events_from_references(
            doc,
            rules={"citation_event_recovery_trigger_max_existing_events": 0},
        )
        self.assertEqual(report.get("status"), "skipped_existing_events_above_dynamic_threshold")
        self.assertEqual(len(recovered.citations), 1)

    def test_ambiguous_author_year_match_is_not_mapped(self) -> None:
        paper = _paper()
        doc = DocumentIR(
            paper=paper,
            chunks=[_chunk("c1", "Prior studies (Smith, 2011) show similar trends.", 10, 11)],
            references=[
                ReferenceEntry(paper_source=paper.paper_source, md_path=paper.md_path, ref_num=1, raw="Smith, A. (2011). Ref A."),
                ReferenceEntry(paper_source=paper.paper_source, md_path=paper.md_path, ref_num=2, raw="Smith, B. (2011). Ref B."),
            ],
            citations=[],
        )
        recovered, report = recover_citation_events_from_references(
            doc,
            rules={"citation_event_recovery_author_year_enabled": True},
        )
        self.assertEqual(report.get("status"), "empty_result")
        self.assertEqual(report.get("recovered_events"), 0)
        self.assertEqual(len(recovered.citations), 0)


if __name__ == "__main__":
    unittest.main()
