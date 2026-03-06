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
