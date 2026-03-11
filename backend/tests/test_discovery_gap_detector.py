from app.discovery.gap_detector import detect_knowledge_gaps


def test_gap_detector_fallback_is_stable():
    rows = detect_knowledge_gaps(domain="granular_flow", limit=2)
    assert len(rows) >= 1
    assert all("gap_id" in r for r in rows)
    assert all("description" in r for r in rows)


def test_gap_detector_returns_source_community_ids_instead_of_proposition_ids(monkeypatch):
    import app.discovery.gap_detector as gap_detector

    class _FakeNeo4jClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list_global_community_rows(self, limit=50000):
            return [
                {
                    "community_id": "gc:demo",
                    "title": "Finite element stability",
                    "summary": "Claims and textbook entities about FEM stability.",
                    "member_count": 4,
                    "paper_support_count": 1,
                    "paper_challenge_count": 2,
                    "textbook_member_count": 2,
                }
            ]

    monkeypatch.setattr(gap_detector, "Neo4jClient", _FakeNeo4jClient)

    rows = detect_knowledge_gaps(domain="finite_element", limit=4)

    assert rows[0].get("source_community_ids") == ["gc:demo"]
    assert "source_proposition_ids" not in rows[0]

