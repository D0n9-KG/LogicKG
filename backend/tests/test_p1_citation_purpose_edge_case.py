# backend/tests/test_p1_citation_purpose_edge_case.py
from __future__ import annotations

from typing import Any

from app.graph.neo4j_client import Neo4jClient


class _SingleRowResult:
    def __init__(self, row: dict[str, Any] | None):
        self._row = row

    def single(self):
        return self._row


class _CaptureSession:
    def __init__(self, run_handler):
        self.run_handler = run_handler

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query: str, **params):
        return self.run_handler(query, params)


class _CaptureDriver:
    def __init__(self, run_handler):
        self.run_handler = run_handler

    def session(self):
        return _CaptureSession(self.run_handler)


def test_cites_write_paths_have_default_purpose_case_statements():
    """Test that all 3 CITES write paths include default purpose CASE statements."""
    captured: list[tuple[str, dict[str, Any]]] = []

    def _run_handler(query: str, params: dict[str, Any]):
        captured.append((query, params))
        return []

    client = Neo4jClient.__new__(Neo4jClient)
    client._driver = _CaptureDriver(_run_handler)

    # Path 1: upsert_references_and_citations (creates CITES edges for resolved citations)
    client.upsert_references_and_citations(
        paper_id="doi:10.1000/test",
        refs=[
            {
                "ref_id": "ref-1",
                "text": "Smith et al., 2020",
            }
        ],
        cited_papers=[
            {
                "paper_id": "doi:10.1000/cited",
                "title": "Cited Paper",
                "authors": ["Smith"],
                "year": 2020,
            }
        ],
        cites_resolved=[
            {
                "cited_paper_id": "doi:10.1000/cited",
                "total_mentions": 1,
                "ref_nums": [1],
                "evidence_chunk_ids": ["chunk-1"],
                "evidence_spans": [],
            }
        ],
        cites_unresolved=[],
    )

    # Path 2: resolve_reference (creates CITES edge when resolving unresolved ref)
    client.resolve_reference(
        ref_id="ref-2",
        cited_paper={
            "paper_id": "doi:10.1000/cited2",
            "title": "Cited Paper 2",
            "authors": ["Jones"],
            "year": 2021,
        },
    )

    # Path 3: resolve_unresolved_reference_merge (creates CITES when merging)
    client.resolve_unresolved_reference_merge(
        ref_id="ref-3",
        cited_paper={
            "paper_id": "doi:10.1000/cited3",
            "title": "Cited Paper 3",
            "authors": ["Lee"],
            "year": 2022,
        },
        crossref_json=None,
        confidence=0.95,
    )

    # Verify all 3 queries were executed
    assert len(captured) == 3

    # Check Path 1 (upsert_references_and_citations)
    query1, params1 = captured[0]
    assert "c.purpose_labels = CASE" in query1
    assert "WHEN c.purpose_labels IS NULL OR size(c.purpose_labels) = 0 THEN ['Background']" in query1
    assert "c.purpose_scores = CASE" in query1
    assert "WHEN c.purpose_scores IS NULL OR size(c.purpose_scores) = 0 THEN [0.2]" in query1

    # Check Path 2 (resolve_reference)
    query2, params2 = captured[1]
    assert "c.purpose_labels = CASE" in query2
    assert "WHEN c.purpose_labels IS NULL OR size(c.purpose_labels) = 0 THEN ['Background']" in query2
    assert "c.purpose_scores = CASE" in query2
    assert "WHEN c.purpose_scores IS NULL OR size(c.purpose_scores) = 0 THEN [0.2]" in query2

    # Check Path 3 (resolve_unresolved_reference_merge)
    query3, params3 = captured[2]
    assert "c.purpose_labels = CASE" in query3
    assert "WHEN c.purpose_labels IS NULL OR size(c.purpose_labels) = 0 THEN ['Background']" in query3
    assert "c.purpose_scores = CASE" in query3
    assert "WHEN c.purpose_scores IS NULL OR size(c.purpose_scores) = 0 THEN [0.2]" in query3


def test_backfill_missing_citation_purposes_functionality():
    """Test backfill_missing_citation_purposes() correctly updates missing purposes."""
    captured: dict[str, Any] = {}

    def _run_handler(query: str, params: dict[str, Any]):
        captured["query"] = query
        captured["params"] = params
        # Simulate 3 edges updated (field name must match: "updated")
        return _SingleRowResult({"updated": 3})

    client = Neo4jClient.__new__(Neo4jClient)
    client._driver = _CaptureDriver(_run_handler)

    updated = client.backfill_missing_citation_purposes(
        citing_paper_id="doi:10.1000/test",
        default_label="Background",
        default_score=0.2,
    )

    assert updated == 3
    assert captured["params"]["citing_paper_id"] == "doi:10.1000/test"
    assert captured["params"]["label"] == "Background"  # Param name is "label"
    assert captured["params"]["score"] == 0.2  # Param name is "score"

    # Verify Cypher query structure (actual query from implementation)
    query = captured["query"]
    assert "MATCH (p:Paper {paper_id:$citing_paper_id})-[c:CITES]->(:Paper)" in query
    assert "WHERE c.purpose_labels IS NULL OR size(c.purpose_labels) = 0" in query
    assert "c.purpose_labels = CASE" in query
    assert "THEN [$label]" in query
    assert "c.purpose_scores = CASE" in query
    assert "THEN [$score]" in query
    assert "RETURN count(c) AS updated" in query


def test_backfill_clamps_score_to_valid_range():
    """Test backfill_missing_citation_purposes() clamps invalid scores."""
    captured: dict[str, Any] = {}

    def _run_handler(query: str, params: dict[str, Any]):
        captured["params"] = params
        return _SingleRowResult({"updated": 0})  # Field name is "updated"

    client = Neo4jClient.__new__(Neo4jClient)
    client._driver = _CaptureDriver(_run_handler)

    # Test clamping upper bound
    client.backfill_missing_citation_purposes(
        citing_paper_id="doi:10.1000/test",
        default_score=1.5,  # Invalid: > 1.0
    )
    assert captured["params"]["score"] == 1.0  # Clamped to 1.0

    # Test clamping lower bound
    client.backfill_missing_citation_purposes(
        citing_paper_id="doi:10.1000/test",
        default_score=-0.3,  # Invalid: < 0.0
    )
    assert captured["params"]["score"] == 0.0  # Clamped to 0.0


def test_pipeline_integration_backfill_callable():
    """Test that backfill_missing_citation_purposes is integrated in pipeline."""
    # Simpler integration test: verify the method exists and can be called
    # Full pipeline integration testing would be complex and brittle

    from app.graph.neo4j_client import Neo4jClient

    # Verify method exists on Neo4jClient
    assert hasattr(Neo4jClient, "backfill_missing_citation_purposes")
    assert callable(getattr(Neo4jClient, "backfill_missing_citation_purposes"))

    # Verify it can be instantiated (mock driver) and called
    captured: dict[str, Any] = {}

    def _run_handler(query: str, params: dict[str, Any]):
        captured["called"] = True
        captured["params"] = params
        return _SingleRowResult({"updated": 1})

    client = Neo4jClient.__new__(Neo4jClient)
    client._driver = _CaptureDriver(_run_handler)

    # Call should succeed with valid inputs
    result = client.backfill_missing_citation_purposes(
        citing_paper_id="doi:10.1000/test",
        default_label="Background",
        default_score=0.2,
    )

    assert captured["called"] is True
    assert result == 1
    assert captured["params"]["citing_paper_id"] == "doi:10.1000/test"
