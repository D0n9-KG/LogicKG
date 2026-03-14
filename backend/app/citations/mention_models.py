from __future__ import annotations

from pydantic import BaseModel, Field

from app.ingest.models import CitationEvent


class CitationMentionRecord(BaseModel):
    mention_id: str
    citation_id: str
    citing_paper_id: str
    cited_paper_id: str
    ref_num: int
    source_chunk_id: str
    span_start: int
    span_end: int
    section: str = 'unknown'
    context_text: str = ''
    target_scopes: list[str] = Field(default_factory=lambda: ['paper'])
    source: str = 'machine'


def build_citation_mention_record(
    *,
    citing_paper_id: str,
    event: CitationEvent,
    cited_paper_id: str,
    citation_id: str,
    section: str | None,
) -> CitationMentionRecord:
    normalized_section = str(section or '').strip().lower() or 'unknown'
    return CitationMentionRecord(
        mention_id=(
            f"cmention:{str(citing_paper_id or '').strip()}:"
            f"{int(event.cited_ref_num)}:{str(event.chunk_id or '').strip()}:"
            f"{int(event.span.start_line)}-{int(event.span.end_line)}"
        ),
        citation_id=str(citation_id or '').strip(),
        citing_paper_id=str(citing_paper_id or '').strip(),
        cited_paper_id=str(cited_paper_id or '').strip(),
        ref_num=int(event.cited_ref_num),
        source_chunk_id=str(event.chunk_id or '').strip(),
        span_start=int(event.span.start_line),
        span_end=int(event.span.end_line),
        section=normalized_section,
        context_text=str(event.context or '').strip(),
        target_scopes=['paper'],
        source='machine',
    )
