# backend/tests/test_ingest_pipeline_reingest_idempotency.py
"""
Tests that re-ingesting a paper via ingest_markdowns deletes stale data first.

Root cause: ingest_markdowns only did upserts, never cleared prior subgraph.
Fix: Before upsert_paper_and_chunks, check if paper exists; if so, delete_paper_subgraph.
"""
from __future__ import annotations

from pathlib import Path

from app.graph.neo4j_client import paper_id_for_md_path
from app.ingest import pipeline
from app.ingest.models import DocumentIR, PaperDraft


class _FakeNeo4jClient:
    """Fake Neo4jClient that tracks method calls and simulates paper existence."""

    def __init__(self, paper_exists: bool) -> None:
        self.paper_exists = paper_exists
        self.calls: list[tuple[str, str | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    def ensure_schema(self) -> None:
        self.calls.append(("ensure_schema", None))

    def get_paper_basic(self, paper_id: str) -> dict:
        """Raises KeyError if paper doesn't exist (mimics real Neo4jClient)."""
        self.calls.append(("get_paper_basic", paper_id))
        if not self.paper_exists:
            raise KeyError(f"Paper not found: {paper_id}")
        return {"paper_id": paper_id}

    def delete_paper_subgraph(self, paper_id: str) -> None:
        self.calls.append(("delete_paper_subgraph", paper_id))

    def upsert_paper_and_chunks(self, doc: DocumentIR) -> None:  # noqa: ARG002
        self.calls.append(("upsert_paper_and_chunks", doc.paper.doi))

    def update_paper_props(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003, ARG002
        pass

    def upsert_figures(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003, ARG002
        pass

    def upsert_references_and_citations(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003, ARG002
        pass

    def upsert_logic_steps_and_claims(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003, ARG002
        self.calls.append(("upsert_logic_steps_and_claims", None))

    def apply_human_claim_evidence_overrides(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003, ARG002
        pass

    def apply_human_logic_step_evidence_overrides(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003, ARG002
        pass

    def update_cites_purposes(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003, ARG002
        pass

    def backfill_missing_citation_purposes(self, *args, **kwargs) -> int:  # noqa: ANN002, ANN003, ARG002
        return 0

    def list_logic_step_structured_rows(self, *args, **kwargs) -> list[dict]:  # noqa: ANN002, ANN003, ARG002
        return []

    def list_claim_structured_rows(self, *args, **kwargs) -> list[dict]:  # noqa: ANN002, ANN003, ARG002
        return []

    def list_global_community_rows(self, *args, **kwargs) -> list[dict]:  # noqa: ANN002, ANN003, ARG002
        return []

    def list_global_community_members(self, *args, **kwargs) -> list[dict]:  # noqa: ANN002, ANN003, ARG002
        return []


def _mock_document() -> DocumentIR:
    """Create a minimal DocumentIR for testing."""
    return DocumentIR(
        paper=PaperDraft(
            paper_source="test_paper_1",
            md_path="C:/tmp/test_paper_1.md",
            title="Test Paper Title",
            title_alt=None,
            authors=[],
            doi="10.1000/TEST123",
            year=2024,
        ),
        chunks=[],
        references=[],
        citations=[],
    )


def _patch_pipeline_dependencies(monkeypatch, fake_neo4j_client):  # noqa: ANN001, ANN201
    """Monkeypatch all external dependencies in pipeline.ingest_markdowns."""
    doc = _mock_document()

    # Neo4j
    monkeypatch.setattr(
        pipeline,
        "Neo4jClient",
        lambda *args, **kwargs: fake_neo4j_client,  # noqa: ARG005
    )

    # Parsing and document building
    monkeypatch.setattr(pipeline, "parse_mineru_markdown", lambda _md: doc)
    monkeypatch.setattr(
        pipeline,
        "recover_references_with_agent",
        lambda d, **kwargs: (d, {"before_refs": 0, "after_refs": 0}),  # noqa: ARG005
    )
    monkeypatch.setattr(
        pipeline,
        "recover_citation_events_from_references",
        lambda d, **kwargs: (d, {"before_events": 0, "after_events": 0}),  # noqa: ARG005
    )

    # Crossref
    monkeypatch.setattr(pipeline, "CrossrefClient", lambda: object())
    monkeypatch.setattr(
        pipeline,
        "build_reference_and_cite_records",
        lambda *args, **kwargs: {  # noqa: ARG005
            "paper_id": None,
            "refs": [],
            "cited_papers": [],
            "cites_resolved": [],
            "cites_unresolved": [],
        },
    )

    # Schema and metadata
    monkeypatch.setattr(pipeline, "load_canonical_meta", lambda _p: {"paper_type": "research"})
    monkeypatch.setattr(
        pipeline,
        "load_active",
        lambda _t: {"version": 1, "paper_type": "research", "rules": {}, "prompts": {}},
    )

    # Figures and FAISS
    monkeypatch.setattr(pipeline, "extract_figures_from_markdown", lambda **kwargs: [])  # noqa: ARG005
    monkeypatch.setattr(pipeline, "build_faiss_for_chunks", lambda *args, **kwargs: None)  # noqa: ARG005

    # File I/O
    monkeypatch.setattr(pipeline, "_write_document_ir", lambda *args, **kwargs: None)  # noqa: ARG005
    monkeypatch.setattr(Path, "write_text", lambda self, *args, **kwargs: 0)  # noqa: ARG005


def test_reingest_existing_paper_deletes_before_upsert(monkeypatch):  # noqa: ANN001, ANN201
    """
    When re-ingesting a paper that already exists in Neo4j, delete_paper_subgraph
    must be called BEFORE upsert_paper_and_chunks to clear stale data.
    """
    fake = _FakeNeo4jClient(paper_exists=True)
    _patch_pipeline_dependencies(monkeypatch, fake)

    pipeline.ingest_markdowns(["dummy.md"])

    expected_paper_id = paper_id_for_md_path("C:/tmp/test_paper_1.md", doi="10.1000/TEST123")

    # Verify existence check was performed
    assert ("get_paper_basic", expected_paper_id) in fake.calls

    # Verify delete was called (since paper exists)
    assert ("delete_paper_subgraph", expected_paper_id) in fake.calls

    # Verify delete comes BEFORE upsert
    delete_idx = fake.calls.index(("delete_paper_subgraph", expected_paper_id))
    upsert_idx = fake.calls.index(("upsert_paper_and_chunks", "10.1000/TEST123"))
    assert delete_idx < upsert_idx, "delete_paper_subgraph must be called before upsert_paper_and_chunks"


def test_first_ingest_skips_delete_when_paper_missing(monkeypatch):  # noqa: ANN001, ANN201
    """
    When ingesting a paper for the first time (doesn't exist in Neo4j yet),
    delete_paper_subgraph should NOT be called.
    """
    fake = _FakeNeo4jClient(paper_exists=False)
    _patch_pipeline_dependencies(monkeypatch, fake)

    pipeline.ingest_markdowns(["dummy.md"])

    # Verify no delete was called
    assert all(name != "delete_paper_subgraph" for name, _ in fake.calls), (
        "delete_paper_subgraph should not be called for first-time ingest"
    )

    # Verify upsert was still called
    assert any(name == "upsert_paper_and_chunks" for name, _ in fake.calls), (
        "upsert_paper_and_chunks must be called even when paper doesn't pre-exist"
    )


def test_ingest_markdowns_builds_community_corpus_without_proposition_writes_or_clustering(monkeypatch):  # noqa: ANN001, ANN201
    class _CommunityNeo4jClient(_FakeNeo4jClient):
        def upsert_proposition_mentions_for_claims(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("paper ingest should not write proposition mentions")

        def list_global_community_rows(self, *args, **kwargs) -> list[dict]:  # noqa: ANN002, ANN003, ARG002
            return [
                {
                    "community_id": "gc:demo",
                    "title": "Finite element stability",
                    "summary": "Claims and textbook entities about FEM stability.",
                    "keywords": ["finite element", "stability"],
                }
            ]

        def list_global_community_members(self, community_id: str, *args, **kwargs) -> list[dict]:  # noqa: ANN002, ANN003
            assert community_id == "gc:demo"
            return [{"member_id": "cl-1", "member_kind": "Claim", "text": "FEM improves stability."}]

    fake = _CommunityNeo4jClient(paper_exists=False)
    _patch_pipeline_dependencies(monkeypatch, fake)

    expected_paper_id = paper_id_for_md_path("C:/tmp/test_paper_1.md", doi="10.1000/TEST123")
    progress_stages: list[str] = []
    built_row_corpora: list[tuple[str, list[dict]]] = []

    monkeypatch.setattr(
        pipeline,
        "build_reference_and_cite_records",
        lambda *args, **kwargs: {  # noqa: ARG005
            "paper_id": expected_paper_id,
            "refs": [],
            "cited_papers": [],
            "cites_resolved": [],
            "cites_unresolved": [],
        },
    )
    monkeypatch.setattr(
        pipeline,
        "run_phase1_extraction",
        lambda **kwargs: {  # noqa: ARG005
            "logic": {"steps": []},
            "validated_claims": [
                {
                    "claim_id": "cl-1",
                    "text": "FEM improves stability.",
                    "step_type": "Result",
                    "confidence": 0.91,
                }
            ],
            "quality_report": {
                "gate_passed": True,
                "quality_tier": "green",
                "quality_tier_score": 0.92,
            },
            "claim_candidates": [],
            "claims_merged": [],
            "rejected_claims": [],
            "step_order": [],
        },
    )
    monkeypatch.setattr(
        pipeline,
        "classify_citation_purposes_batch",
        lambda **kwargs: {"by_id": {}},  # noqa: ARG005
    )
    monkeypatch.setattr(
        pipeline,
        "build_faiss_for_rows",
        lambda rows, out_dir, **kwargs: built_row_corpora.append((str(out_dir), list(rows))),  # noqa: ARG005
    )

    result = pipeline.ingest_markdowns(
        ["dummy.md"],
        progress=lambda stage, p, msg=None: progress_stages.append(stage),  # noqa: ARG005
    )

    assert not any(stage == "ingest:clustering" for stage in progress_stages)
    assert result["clustering"]["triggered"] is False
    assert all("propositions" not in out_dir for out_dir, _ in built_row_corpora)
    community_corpus = next(rows for out_dir, rows in built_row_corpora if out_dir.endswith("communities"))
    assert len(community_corpus) == 1
    assert community_corpus[0]["kind"] == "community"
    assert community_corpus[0]["source_id"] == "gc:demo"
    assert community_corpus[0]["community_id"] == "gc:demo"
    assert community_corpus[0]["member_ids"] == ["cl-1"]
    assert community_corpus[0]["member_kinds"] == ["Claim"]
    assert community_corpus[0]["keyword_texts"] == ["finite element", "stability"]
    assert community_corpus[0]["text"] == (
        "Finite element stability\n"
        "Claims and textbook entities about FEM stability.\n"
        "keywords: finite element, stability"
    )
