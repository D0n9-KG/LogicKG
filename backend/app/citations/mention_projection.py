from __future__ import annotations

from app.citations.mention_models import build_citation_mention_record
from app.ingest.models import DocumentIR


def build_citation_mention_rows(
    *,
    doc: DocumentIR,
    paper_id: str,
    cite_rec: dict | None,
    citation_acts: list[dict] | None,
) -> list[dict]:
    chunk_section_by_id = {
        str(chunk.chunk_id): str(chunk.section or '').strip()
        for chunk in (doc.chunks or [])
        if str(chunk.chunk_id).strip()
    }

    cited_by_ref_num: dict[int, str] = {}
    for item in (cite_rec or {}).get('cites_resolved') or []:
        cited_paper_id = str(item.get('cited_paper_id') or '').strip()
        if not cited_paper_id:
            continue
        for ref_num in item.get('ref_nums') or []:
            try:
                cited_by_ref_num[int(ref_num)] = cited_paper_id
            except Exception:
                continue

    citation_id_by_cited: dict[str, str] = {}
    for item in citation_acts or []:
        cited_paper_id = str(item.get('cited_paper_id') or '').strip()
        citation_id = str(item.get('citation_id') or '').strip()
        if cited_paper_id and citation_id:
            citation_id_by_cited[cited_paper_id] = citation_id

    rows: list[dict] = []
    for event in doc.citations or []:
        try:
            ref_num = int(event.cited_ref_num)
        except Exception:
            continue
        cited_paper_id = cited_by_ref_num.get(ref_num)
        if not cited_paper_id:
            continue
        citation_id = citation_id_by_cited.get(cited_paper_id) or f'citeact:{paper_id}->{cited_paper_id}'
        section = chunk_section_by_id.get(str(event.chunk_id).strip()) or 'unknown'
        mention = build_citation_mention_record(
            citing_paper_id=paper_id,
            event=event,
            cited_paper_id=cited_paper_id,
            citation_id=citation_id,
            section=section,
        )
        rows.append(mention.model_dump())
    return rows
