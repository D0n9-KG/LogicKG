from __future__ import annotations

from research_logic.route_builder.topic_scope_builder import build_topic_scope_candidates


def test_topic_scope_builder_uses_cross_paper_communities_as_candidates() -> None:
    candidates = build_topic_scope_candidates(
        communities=[
            {
                'community_id': 'c1',
                'title': 'Relation-aware graph reasoning',
                'paper_count': 4,
                'member_ids': ['a', 'b'],
            },
            {
                'community_id': 'c2',
                'title': 'Single-paper residue',
                'paper_count': 1,
                'member_ids': ['x'],
            },
        ]
    )

    assert candidates[0]['topic_scope'] == 'Relation-aware graph reasoning'
    assert candidates[0]['paper_count'] == 4
    assert all(row['paper_count'] >= 2 for row in candidates)
