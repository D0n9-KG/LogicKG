from app.discovery.service import run_discovery_batch


def test_discovery_batch_outputs_structured_candidates():
    out = run_discovery_batch(
        domain="granular_flow",
        dry_run=True,
        max_gaps=4,
        candidates_per_gap=2,
        use_llm=False,
        hop_order=2,
        adjacent_samples=5,
        random_samples=1,
        rag_top_k=3,
        prompt_optimize=False,
        community_method="hybrid",
        community_samples=3,
        prompt_optimization_method="rl_bandit",
    )
    assert "candidates" in out
    assert "gaps" in out
    assert out["settings"]["max_gaps"] == 4
    assert out["settings"]["candidates_per_gap"] == 2
    assert out["settings"]["hop_order"] == 2
    assert out["settings"]["adjacent_samples"] == 5
    assert out["settings"]["random_samples"] == 1
    assert out["settings"]["rag_top_k"] == 3
    assert out["settings"]["prompt_optimize"] is False
    assert out["settings"]["community_method"] == "hybrid"
    assert out["settings"]["community_samples"] == 3
    assert out["settings"]["prompt_optimization_method"] == "rl_bandit"
    assert all("support_evidence_ids" in c for c in out["candidates"])
    assert all("motivation" in c for c in out["candidates"])
    assert all("gap_type" in c for c in out["candidates"])


def test_discovery_batch_uses_source_claims_for_support(monkeypatch):
    import app.discovery.service as svc

    monkeypatch.setattr(
        svc,
        "detect_knowledge_gaps",
        lambda domain, limit: [
            {
                "gap_id": "gap:test:1",
                "gap_type": "gap_claim",
                "description": "Need causal explanation for force-chain collapse in dense regime.",
                "missing_evidence_statement": "Need cross-paper evidence.",
                "priority_score": 0.8,
                "source_claim_ids": ["claim:test:1"],
            }
        ],
    )
    monkeypatch.setattr(
        svc,
        "generate_candidate_questions",
        lambda gaps, **kwargs: [
            {
                "candidate_id": "rq:test:1",
                "question": "What causal mechanism explains force-chain collapse in dense regime?",
                "gap_id": "gap:test:1",
                "gap_type": "gap_claim",
                "source_claim_ids": ["claim:test:1"],
                "novelty_score": 0.7,
                "feasibility_score": 0.6,
                "relevance_score": 0.8,
            }
        ],
    )

    out = run_discovery_batch(domain="granular_flow", dry_run=False, use_llm=False)
    assert len(out["candidates"]) == 1
    support_ids = out["candidates"][0]["support_evidence_ids"]
    assert any(str(x).startswith("CL:claim:test:1") for x in support_ids)


def test_discovery_batch_uses_source_communities_for_support(monkeypatch):
    import app.discovery.evidence_auditor as auditor
    import app.discovery.service as svc

    class _FakeNeo4jClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list_global_community_members(self, community_id: str, limit: int = 200):
            assert community_id == "gc:demo"
            return [{"member_id": "claim:test:1", "member_kind": "Claim", "text": "FEM improves stability."}]

    monkeypatch.setattr(
        svc,
        "detect_knowledge_gaps",
        lambda domain, limit: [
            {
                "gap_id": "gap:community:1",
                "gap_type": "gap_claim",
                "description": "Need community-level explanation for FEM stability disagreement.",
                "missing_evidence_statement": "Need member-backed evidence across papers.",
                "priority_score": 0.8,
                "source_community_ids": ["gc:demo"],
            }
        ],
    )
    monkeypatch.setattr(
        svc,
        "generate_candidate_questions",
        lambda gaps, **kwargs: [
            {
                "candidate_id": "rq:community:1",
                "question": "What community-level mechanism explains FEM stability disagreement?",
                "gap_id": "gap:community:1",
                "gap_type": "gap_claim",
                "source_community_ids": ["gc:demo"],
                "novelty_score": 0.7,
                "feasibility_score": 0.6,
                "relevance_score": 0.8,
            }
        ],
    )
    monkeypatch.setattr(auditor, "Neo4jClient", _FakeNeo4jClient)

    out = run_discovery_batch(domain="granular_flow", dry_run=False, use_llm=False)

    assert len(out["candidates"]) == 1
    candidate = out["candidates"][0]
    assert candidate["source_community_ids"] == ["gc:demo"]
    assert any(str(x).startswith("GC:gc:demo") for x in candidate["support_evidence_ids"])


def test_discovery_batch_attaches_hybrid_context(monkeypatch):
    import app.discovery.service as svc

    monkeypatch.setattr(
        svc,
        "detect_knowledge_gaps",
        lambda domain, limit: [
            {
                "gap_id": "gap:test:ctx",
                "gap_type": "gap_claim",
                "description": "Need better mechanism hypothesis",
                "missing_evidence_statement": "Need cross-paper support.",
                "priority_score": 0.7,
            }
        ],
    )
    monkeypatch.setattr(
        svc,
        "generate_candidate_questions",
        lambda gaps, **kwargs: [
            {
                "candidate_id": "rq:test:ctx",
                "question": "What mechanism explains the unresolved evidence pattern?",
                "gap_id": "gap:test:ctx",
                "gap_type": "gap_claim",
                "novelty_score": 0.6,
                "feasibility_score": 0.7,
                "relevance_score": 0.8,
            }
        ],
    )
    monkeypatch.setattr(
        svc,
        "build_hybrid_context_for_gap",
        lambda **kwargs: {
            "graph_context_summary": "graph-summary",
            "rag_context_snippets": ["chunk-a", "chunk-b"],
            "source_paper_ids": ["doi:10.1/x"],
            "inspiration_adjacent_paper_ids": ["doi:10.1/adj"],
            "inspiration_random_paper_ids": ["doi:10.1/rand"],
            "inspiration_community_paper_ids": ["doi:10.1/com"],
        },
        raising=False,
    )

    out = run_discovery_batch(
        domain="granular_flow",
        dry_run=True,
        use_llm=False,
        hop_order=2,
        adjacent_samples=4,
        random_samples=2,
        rag_top_k=3,
        prompt_optimize=True,
        community_method="hybrid",
        community_samples=4,
        prompt_optimization_method="rl_bandit",
    )
    assert len(out["candidates"]) == 1
    item = out["candidates"][0]
    assert item.get("graph_context_summary") == "graph-summary"
    assert item.get("rag_context_snippets") == ["chunk-a", "chunk-b"]
    assert item.get("source_paper_ids") == ["doi:10.1/x"]
    assert item.get("inspiration_adjacent_paper_ids") == ["doi:10.1/adj"]
    assert item.get("inspiration_random_paper_ids") == ["doi:10.1/rand"]
    assert item.get("inspiration_community_paper_ids") == ["doi:10.1/com"]


def test_discovery_batch_forwards_prompt_optimization_method(monkeypatch):
    import app.discovery.service as svc

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        svc,
        "detect_knowledge_gaps",
        lambda domain, limit: [
            {
                "gap_id": "gap:test:rl",
                "gap_type": "gap_claim",
                "description": "Need mechanism-level explanation",
                "priority_score": 0.6,
            }
        ],
    )

    def _fake_generate(gaps, **kwargs):
        captured.update(kwargs)
        return [
            {
                "candidate_id": "rq:test:rl",
                "question": "What mechanism explains this gap?",
                "gap_id": "gap:test:rl",
                "gap_type": "gap_claim",
                "novelty_score": 0.6,
                "feasibility_score": 0.7,
                "relevance_score": 0.8,
            }
        ]

    monkeypatch.setattr(svc, "generate_candidate_questions", _fake_generate)

    out = run_discovery_batch(
        domain="granular_flow",
        dry_run=True,
        use_llm=False,
        prompt_optimize=True,
        prompt_optimization_method="rl_bandit",
    )

    assert out["settings"]["prompt_optimization_method"] == "rl_bandit"
    assert captured.get("prompt_optimization_method") == "rl_bandit"
