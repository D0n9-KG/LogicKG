from __future__ import annotations

from typing import Any


def build_topic_scope_candidates(communities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in communities:
        paper_count = int(row.get('paper_count') or 0)
        if paper_count < 2:
            continue
        candidates.append(
            {
                'topic_scope': str(row.get('title') or '').strip(),
                'community_id': str(row.get('community_id') or '').strip(),
                'paper_count': paper_count,
                'member_ids': [str(member_id).strip() for member_id in (row.get('member_ids') or []) if str(member_id).strip()],
            }
        )
    return candidates
