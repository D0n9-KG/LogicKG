from app.discovery.context_builder import build_hybrid_context_for_gap


def test_context_builder_dry_run_has_required_fields():
    out = build_hybrid_context_for_gap(
        domain="granular_flow",
        gap={
            "gap_id": "gap:test:ctx",
            "description": "Need mechanism-level explanation of unresolved contradiction.",
            "missing_evidence_statement": "Need support/challenge evidence across papers.",
            "source_paper_ids": ["doi:10.0/test"],
        },
        question="What mechanism resolves this contradiction?",
        hop_order=2,
        adjacent_samples=4,
        random_samples=1,
        rag_top_k=3,
        dry_run=True,
    )
    assert isinstance(out.get("graph_context_summary"), str)
    assert isinstance(out.get("rag_context_snippets"), list)
    assert out.get("source_paper_ids") == ["doi:10.0/test"]
    assert "inspiration_adjacent_paper_ids" in out
    assert "inspiration_community_paper_ids" in out
    assert "inspiration_random_paper_ids" in out


def test_context_builder_resolves_source_papers_from_source_community_ids(monkeypatch):
    import app.discovery.context_builder as context_builder

    captured: dict[str, object] = {}

    class _FakeNeo4jClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list_global_community_members(self, community_id: str, limit: int = 200):
            assert community_id == "gc:demo"
            return [
                {"member_id": "claim:test:1", "member_kind": "Claim", "text": "FEM improves stability."},
                {"member_id": "ke:test:1", "member_kind": "KnowledgeEntity", "text": "Finite Element Method"},
            ]

        def list_paper_ids_for_claims(self, claim_ids, limit: int = 80):
            assert claim_ids == ["claim:test:1"]
            return ["doi:10.0/source"]

        def sample_inspiration_papers(self, target_paper_ids, **kwargs):
            captured["target_paper_ids"] = list(target_paper_ids)
            return {
                "adjacent_papers": [],
                "community_papers": [],
                "random_papers": [],
            }

        def list_papers_by_ids(self, paper_ids, limit: int = 300):
            assert paper_ids == ["doi:10.0/source"]
            return [{"paper_id": "doi:10.0/source", "paper_source": "paper-A", "title": "Paper A"}]

        def get_citation_context_by_paper_source(self, paper_sources, limit: int = 60):
            return []

        def get_structured_knowledge_for_papers(self, paper_sources, max_claims: int = 18, max_steps: int = 10):
            return {"claims": [], "logic_steps": []}

    monkeypatch.setattr(context_builder, "Neo4jClient", _FakeNeo4jClient)
    monkeypatch.setattr(context_builder, "_retrieve_rag_snippets", lambda *args, **kwargs: [], raising=False)

    out = context_builder.build_hybrid_context_for_gap(
        domain="finite_element",
        gap={
            "gap_id": "gap:community:test",
            "description": "Need better cross-paper support for FEM stability boundaries.",
            "source_community_ids": ["gc:demo"],
        },
        question="What mechanism explains the unresolved FEM stability pattern?",
        dry_run=False,
    )

    assert out["source_paper_ids"] == ["doi:10.0/source"]
    assert captured["target_paper_ids"] == ["doi:10.0/source"]
