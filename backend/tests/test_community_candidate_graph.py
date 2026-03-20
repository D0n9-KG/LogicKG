from __future__ import annotations

from app.community.candidate_graph import build_logicstep_candidate_graph


def test_candidate_graph_ignores_same_paper_neighbors_and_keeps_cross_paper_edges() -> None:
    graph = build_logicstep_candidate_graph(
        logic_steps=[
            {'logic_step_id': 'a', 'paper_id': 'p1', 'summary': 'graph encoding'},
            {'logic_step_id': 'b', 'paper_id': 'p2', 'summary': 'relation-aware graph encoding'},
            {'logic_step_id': 'c', 'paper_id': 'p1', 'summary': 'intra paper detail'},
        ],
        similar_logic_edges=[
            {'source': 'a', 'target': 'b', 'score': 0.91},
            {'source': 'a', 'target': 'c', 'score': 0.97},
        ],
        shared_entity_edges=[],
        citation_boosts=[],
    )

    assert graph['nodes'] == ['a', 'b', 'c']
    assert graph['edges'] == [{'source': 'a', 'target': 'b', 'weight': 0.91}]
