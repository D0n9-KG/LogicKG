from __future__ import annotations

import app.community.service as community_service
from app.community.service_v2 import rebuild_global_communities_v2


class _FakeClient:
    def __init__(self) -> None:
        self.communities: list[dict] = []
        self.keywords: list[dict] = []
        self.memberships: list[dict] = []
        self.cleared = False

    def ensure_schema(self) -> None:
        return None

    def list_logic_steps_for_fusion(self, paper_id: str | None = None, limit: int = 50000) -> list[dict]:
        del paper_id, limit
        return [
            {
                'logic_step_id': 'p1:method',
                'paper_id': 'p1',
                'paper_source': 'paper-1',
                'step_type': 'Method',
                'summary': 'Uses relation-aware graph encoding for reasoning.',
                'step_order': 1,
            },
            {
                'logic_step_id': 'p2:problem',
                'paper_id': 'p2',
                'paper_source': 'paper-2',
                'step_type': 'Problem',
                'summary': 'Proposes relation-aware graph representations.',
                'step_order': 1,
            },
        ]

    def list_similar_logic_edges_in_papers(
        self,
        paper_ids: list[str],
        min_score: float = 0.0,
        limit_per_source: int = 2,
        limit_total: int = 3000,
    ) -> list[dict]:
        del paper_ids, min_score, limit_per_source, limit_total
        return [{'source': 'p1:method', 'target': 'p2:problem', 'score': 0.93}]

    def list_shared_entity_logicstep_edges(self, paper_ids: list[str], limit: int = 50000) -> list[dict]:
        del paper_ids, limit
        return []

    def list_paper_citation_pairs(self, paper_ids: list[str], limit: int = 50000) -> list[dict]:
        del paper_ids, limit
        return []

    def clear_global_communities(self) -> dict:
        self.cleared = True
        return {'deleted_communities': 0, 'deleted_keywords': 0, 'deleted_memberships': 0, 'deleted_keyword_edges': 0}

    def upsert_global_communities(self, items: list[dict]) -> int:
        self.communities = list(items)
        return len(items)

    def upsert_global_keywords(self, items: list[dict]) -> int:
        self.keywords = list(items)
        return len(items)

    def replace_global_memberships(self, items: list[dict]) -> int:
        self.memberships = list(items)
        return len(items)


def test_rebuild_global_communities_v2_materializes_cross_paper_logicstep_clusters() -> None:
    client = _FakeClient()

    result = rebuild_global_communities_v2(client=client)

    assert result['communities'] == 1
    assert client.cleared is True
    assert client.communities[0]['paper_count'] == 2
    assert 'relation-aware graph' in client.communities[0]['title'].lower()
    assert any(row['member_id'] == 'p1:method' for row in client.memberships)


def test_rebuild_global_communities_uses_v2_pipeline_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(community_service.settings, 'global_community_use_v2', True)
    monkeypatch.setattr(
        community_service,
        'rebuild_global_communities_v2',
        lambda **_kwargs: {'ok': True, 'version': 'v2'},
    )

    result = community_service.rebuild_global_communities()

    assert result['version'] == 'v2'
