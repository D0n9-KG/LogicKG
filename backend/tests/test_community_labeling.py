from __future__ import annotations

from app.community.labeling import label_community


def test_labeler_prefers_distinctive_method_phrase_over_generic_tokens() -> None:
    label = label_community(
        core_members=[
            {'summary': 'Uses relation-aware graph encoding for reasoning', 'paper_title': 'A'},
            {'summary': 'Proposes relation-aware graph representations', 'paper_title': 'B'},
        ],
        claim_rows=[],
    )

    assert 'relation-aware graph' in label['title'].lower()
    assert label['keywords']
