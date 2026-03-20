from __future__ import annotations

from app.community.overlap_detection import detect_overlapping_communities


def test_detector_allows_logic_step_to_belong_to_multiple_communities() -> None:
    result = detect_overlapping_communities(
        nodes=['a', 'b', 'c'],
        edges=[
            {'source': 'a', 'target': 'b', 'weight': 0.9},
            {'source': 'a', 'target': 'c', 'weight': 0.88},
        ],
        max_memberships_per_node=2,
        min_community_size=2,
    )

    memberships = result['memberships']['a']

    assert len(memberships) == 2
    assert result['communities'][0]['member_ids']
