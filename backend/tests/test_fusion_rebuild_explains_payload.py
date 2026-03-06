from __future__ import annotations

from pathlib import Path

from app.fusion import service


class _FakeClient:
    def __init__(self) -> None:
        self.explains_payload: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def ensure_schema(self):
        return None

    def list_logic_steps_for_fusion(self, paper_id=None, limit=50000):
        return [
            {
                'logic_step_id': 'paper-1:Method',
                'paper_id': 'paper-1',
                'step_type': 'Method',
                'summary': 'Uses density and modulus to build the method.',
                'evidence_chunk_ids': ['chunk-1'],
            }
        ]

    def list_claims_for_fusion(self, paper_id=None, limit=50000):
        return []

    def list_textbook_entities_for_fusion(self, textbook_id=None, limit=50000):
        return [
            {
                'entity_id': 'entity-1',
                'name': 'Density',
                'entity_type': 'entity',
                'source_chapter_id': 'ch-1',
            }
        ]

    def list_textbook_relations_for_fusion(self, textbook_id=None, limit=100000):
        return []

    def create_fusion_explains_edges(self, links):
        self.explains_payload = list(links)
        return len(links)

    def upsert_fusion_communities(self, communities):
        return len(communities)

    def upsert_fusion_keywords(self, keywords):
        return len(keywords)


def test_rebuild_fusion_maps_explains_edges_to_writer_payload(monkeypatch, tmp_path: Path):
    fake_client = _FakeClient()

    monkeypatch.setattr(service, 'Neo4jClient', lambda *args, **kwargs: fake_client)
    monkeypatch.setattr(
        service,
        'build_fusion_projection',
        lambda **kwargs: {
            'nodes': [
                {'id': 'paper-1:Method', 'label': 'LogicStep', 'summary': 'm1'},
                {'id': 'entity-1', 'label': 'KnowledgeEntity', 'name': 'Density'},
            ],
            'edges': [
                {
                    'type': 'EXPLAINS',
                    'source': 'paper-1:Method',
                    'target': 'entity-1',
                    'score': 0.76,
                    'reasons': ['coverage=1.0'],
                    'source_chapter_id': 'ch-1',
                }
            ],
        },
    )
    monkeypatch.setattr(service, 'detect_fusion_communities', lambda *args, **kwargs: [])
    monkeypatch.setattr(service, 'extract_fusion_keywords', lambda *args, **kwargs: [])
    monkeypatch.setattr(service, '_snapshot_file', lambda: tmp_path / 'fusion_snapshot.json')

    result = service.rebuild_fusion_graph()

    assert result['ok'] is True
    assert result['explains_written'] == 1
    assert len(fake_client.explains_payload) == 1

    first = fake_client.explains_payload[0]
    assert first['logic_step_id'] == 'paper-1:Method'
    assert first['entity_id'] == 'entity-1'
    assert float(first['score']) == 0.76
