from __future__ import annotations

from typing import Any


def materialize_community_rows(
    *,
    communities: list[dict[str, Any]],
    memberships: dict[str, list[dict[str, Any]]],
    labels: dict[str, dict[str, Any]],
    logic_steps: list[dict[str, Any]],
    version: str,
    built_at: str,
) -> dict[str, list[dict[str, Any]]]:
    logic_steps_by_id = {
        str(row.get('logic_step_id') or '').strip(): row
        for row in logic_steps
        if str(row.get('logic_step_id') or '').strip()
    }

    community_rows: list[dict[str, Any]] = []
    keyword_rows: list[dict[str, Any]] = []
    membership_rows: list[dict[str, Any]] = []

    for community in communities:
        community_id = str(community.get('community_id') or '').strip()
        if not community_id:
            continue
        member_ids = [str(member_id).strip() for member_id in (community.get('member_ids') or []) if str(member_id).strip()]
        core_member_ids = [
            str(member_id).strip()
            for member_id in (community.get('core_member_ids') or [])
            if str(member_id).strip()
        ]
        label = labels.get(community_id) or {}
        paper_ids = {
            str((logic_steps_by_id.get(member_id) or {}).get('paper_id') or '').strip()
            for member_id in member_ids
            if str((logic_steps_by_id.get(member_id) or {}).get('paper_id') or '').strip()
        }
        community_rows.append(
            {
                'community_id': community_id,
                'title': str(label.get('title') or community_id),
                'summary': str(label.get('summary') or ''),
                'confidence': float(community.get('confidence') or 0.0),
                'member_count': len(member_ids),
                'paper_count': len(paper_ids),
                'core_member_count': len(core_member_ids),
                'version': version,
                'built_at': built_at,
            }
        )

        for rank, keyword in enumerate(label.get('keywords') or [], start=1):
            normalized_keyword = str(keyword or '').strip()
            if not normalized_keyword:
                continue
            keyword_rows.append(
                {
                    'community_id': community_id,
                    'keyword_id': f'{community_id}:kw:{rank}',
                    'keyword': normalized_keyword,
                    'rank': rank,
                    'weight': float(max(1, len(label.get('keywords') or [])) - rank + 1),
                }
            )

    for member_id, member_rows in memberships.items():
        for row in member_rows:
            membership_rows.append(
                {
                    'community_id': str(row.get('community_id') or '').strip(),
                    'member_id': str(member_id or '').strip(),
                    'member_kind': 'LogicStep',
                    'weight': float(row.get('score') or 0.0),
                    'rank': int(row.get('rank') or 0),
                    'is_core': bool(row.get('is_core') or False),
                }
            )

    return {
        'communities': community_rows,
        'keywords': keyword_rows,
        'memberships': membership_rows,
    }
