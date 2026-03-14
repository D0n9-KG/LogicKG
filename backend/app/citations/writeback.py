from __future__ import annotations

from typing import Any


def persist_citation_graph_enrichment(
    *,
    client: Any,
    paper_id: str,
    citation_acts: list[dict] | None,
    citation_mentions: list[dict] | None,
) -> None:
    acts = [dict(item or {}) for item in (citation_acts or []) if isinstance(item, dict)]
    mentions = [dict(item or {}) for item in (citation_mentions or []) if isinstance(item, dict)]
    if acts:
        client.upsert_citation_acts(acts)
    if mentions:
        client.upsert_citation_mentions(mentions)
        client.link_citation_mentions_to_claim_targets(str(paper_id or '').strip())
        client.link_citation_mentions_to_artifact_targets(str(paper_id or '').strip())
