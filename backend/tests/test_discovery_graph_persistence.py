from __future__ import annotations

from app.graph.neo4j_client import Neo4jClient


class _FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, query: str, **params):
        self.calls.append((str(query), dict(params)))
        return []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeDriver:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def session(self):
        return self._session

    def close(self):
        return None


def _client_with_fake_driver(fake_session: _FakeSession) -> Neo4jClient:
    client = object.__new__(Neo4jClient)
    client._driver = _FakeDriver(fake_session)
    return client


def test_upsert_discovery_graph_uses_global_community_edges_instead_of_propositions() -> None:
    fake_session = _FakeSession()
    client = _client_with_fake_driver(fake_session)

    client.upsert_discovery_graph(
        domain='granular_flow',
        batch_id='batch-1',
        built_at='2026-03-11T00:00:00+00:00',
        gaps=[
            {
                'gap_id': 'kg:demo',
                'gap_type': 'coverage_gap',
                'title': 'Finite element benchmarks remain thin',
                'description': 'Need more benchmark coverage.',
                'missing_evidence_statement': 'Benchmark evidence is sparse.',
                'priority_score': 0.82,
                'signals': {'coverage': 0.2},
                'source_claim_ids': ['cl-1'],
                'source_community_ids': ['gc:demo'],
                'source_paper_ids': ['doi:10.1000/example'],
            }
        ],
        questions=[
            {
                'candidate_id': 'rq:demo',
                'gap_id': 'kg:demo',
                'gap_type': 'coverage_gap',
                'question': 'How can finite element benchmarks be broadened?',
                'motivation': 'Benchmark support is sparse.',
                'support_evidence_ids': ['GC:gc:demo', 'CL:cl-1', 'CH:chunk-1'],
                'challenge_evidence_ids': ['GC:gc:counter', 'EV:ev-1'],
                'source_claim_ids': ['cl-1'],
                'source_community_ids': ['gc:demo'],
                'source_paper_ids': ['doi:10.1000/example'],
                'inspiration_adjacent_paper_ids': ['doi:10.1000/example'],
                'inspiration_random_paper_ids': [],
                'inspiration_community_paper_ids': ['doi:10.1000/example'],
            }
        ],
    )

    queries = '\n'.join(query for query, _ in fake_session.calls)

    assert 'GAP_FROM_COMMUNITY' in queries
    assert 'USES_SOURCE_COMMUNITY' in queries
    assert 'MATCH (gc:GlobalCommunity {community_id:id})' in queries
    assert 'SUPPORTED_BY' in queries
    assert 'CHALLENGED_BY' in queries
    assert 'GAP_FROM_PROPOSITION' not in queries
    assert 'MATCH (pr:Proposition' not in queries
