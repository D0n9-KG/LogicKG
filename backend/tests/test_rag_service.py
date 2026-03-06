"""Tests for RAG service helpers (P2-14)."""
from __future__ import annotations

from app.rag.service import (
    _rrf_fuse,
    _build_system_prompt,
    _format_graph_context,
    _format_structured_knowledge,
    _stringify_graph_value,
)


# ── RRF fusion ──


def test_rrf_fuse_single_list():
    """Single ranked list should preserve order."""
    items = [
        {"chunk_id": "c1", "score": 0.9},
        {"chunk_id": "c2", "score": 0.8},
    ]
    fused = _rrf_fuse([items])
    assert [x["chunk_id"] for x in fused] == ["c1", "c2"]
    assert all("rrf_score" in x for x in fused)


def test_rrf_fuse_two_lists_boosts_overlap():
    """Chunks appearing in both lists should rank higher."""
    list_a = [
        {"chunk_id": "c1", "score": 0.9},
        {"chunk_id": "c2", "score": 0.8},
    ]
    list_b = [
        {"chunk_id": "c2", "score": 5.0},
        {"chunk_id": "c3", "score": 3.0},
    ]
    fused = _rrf_fuse([list_a, list_b])
    ids = [x["chunk_id"] for x in fused]
    # c2 appears in both lists → highest RRF score
    assert ids[0] == "c2"
    assert set(ids) == {"c1", "c2", "c3"}


def test_rrf_fuse_deduplicates():
    """Same chunk_id in multiple lists should appear only once."""
    list_a = [{"chunk_id": "c1", "score": 1.0}]
    list_b = [{"chunk_id": "c1", "score": 2.0}]
    fused = _rrf_fuse([list_a, list_b])
    assert len(fused) == 1
    assert fused[0]["chunk_id"] == "c1"


def test_rrf_fuse_empty_lists():
    """Empty input should return empty output."""
    assert _rrf_fuse([]) == []
    assert _rrf_fuse([[], []]) == []


def test_rrf_fuse_skips_missing_chunk_id():
    """Items without chunk_id should be skipped."""
    items = [{"score": 0.9}, {"chunk_id": "c1", "score": 0.8}]
    fused = _rrf_fuse([items])
    assert len(fused) == 1
    assert fused[0]["chunk_id"] == "c1"


def test_rrf_fuse_normalizes_chunk_ids():
    """Whitespace and None chunk_ids should be handled."""
    items = [{"chunk_id": " c1 "}, {"chunk_id": "None"}, {"chunk_id": None}, {"chunk_id": "c2"}]
    fused = _rrf_fuse([items])
    assert [x["chunk_id"] for x in fused] == ["c1", "c2"]


def test_rrf_fuse_dedup_within_same_list():
    """Duplicate chunk_ids within the same list should only count once."""
    items = [
        {"chunk_id": "c1", "score": 0.9},
        {"chunk_id": "c1", "score": 0.5},  # duplicate
        {"chunk_id": "c2", "score": 0.8},
    ]
    fused = _rrf_fuse([items])
    assert len(fused) == 2
    ids = [x["chunk_id"] for x in fused]
    assert "c1" in ids and "c2" in ids


# ── System prompt ──


def test_build_system_prompt_default():
    """Default prompt should use generic scientific assistant."""
    prompt = _build_system_prompt()
    assert "scientific research assistant" in prompt
    assert "mechanics" not in prompt


def test_build_system_prompt_custom():
    """Custom domain prompt should be used."""
    prompt = _build_system_prompt("You are a DEM simulation expert.")
    assert "DEM simulation expert" in prompt
    assert "evidence" in prompt.lower()


def test_build_system_prompt_empty_string():
    """Empty string should fall back to default."""
    prompt = _build_system_prompt("")
    assert "scientific research assistant" in prompt


# ── Graph context formatting ──


def test_format_graph_context_none():
    assert _format_graph_context(None) == ""


def test_format_graph_context_empty_list():
    assert _format_graph_context([]) == ""


def test_format_graph_context_basic():
    ctx = [
        {"source_paper": "Paper A", "target_paper": "Paper B", "relationship": "cites"},
        {"step_type": "Method", "summary": "Uses DEM for simulation"},
    ]
    result = _format_graph_context(ctx)
    assert "Graph Context:" in result
    assert "Paper A" in result
    assert "Method" in result
    assert "DEM" in result


def test_format_graph_context_caps_at_30():
    """Should cap at 30 entries to avoid token overflow."""
    ctx = [{"source_paper": f"P{i}", "relationship": "cites"} for i in range(50)]
    result = _format_graph_context(ctx)
    lines = [l for l in result.split("\n") if l.strip() and l != "Graph Context:"]
    assert len(lines) <= 30


def test_format_graph_context_supports_neo4j_citation_schema():
    """Should include fields returned by get_citation_context_by_paper_source()."""
    ctx = [
        {
            "paper_source": "paper-A",
            "doi": "10.1000/a",
            "cited_doi": "10.1000/b",
            "cited_title": "A cited work",
            "purpose_labels": ["background", "method"],
            "total_mentions": 3,
            "ref_nums": [1, 2],
        }
    ]
    result = _format_graph_context(ctx)
    assert "paper_source=paper-A" in result
    assert "cited_title=A cited work" in result
    assert "purpose_labels=background, method" in result


def test_format_graph_context_skips_non_dict_entries():
    result = _format_graph_context([{"summary": "ok"}, "bad-row", 42, None])
    assert "Graph Context:" in result
    assert "summary=ok" in result


def test_format_graph_context_caps_total_prompt_size():
    """Should bound total graph-context prompt size for long values."""
    long_summary = "x" * 5000
    ctx = [{"summary": long_summary} for _ in range(30)]
    result = _format_graph_context(ctx)
    assert result.startswith("Graph Context:\n")
    assert len(result) <= 6100  # header + some margin


# ── _stringify_graph_value ──


def test_stringify_graph_value_list():
    assert _stringify_graph_value(["a", "b", "c"]) == "a, b, c"


def test_stringify_graph_value_dict():
    result = _stringify_graph_value({"k1": "v1", "k2": "v2"})
    assert "k1=v1" in result


def test_stringify_graph_value_none():
    assert _stringify_graph_value(None) == ""


def test_stringify_graph_value_truncates():
    long = "x" * 500
    result = _stringify_graph_value(long, max_chars=100)
    assert len(result) <= 100
    assert result.endswith("...")


# ── Structured knowledge formatting ──


def test_format_structured_knowledge_none():
    assert _format_structured_knowledge(None) == ""


def test_format_structured_knowledge_empty():
    assert _format_structured_knowledge({"claims": [], "logic_steps": []}) == ""


def test_format_structured_knowledge_logic_steps():
    knowledge = {
        "claims": [],
        "logic_steps": [
            {"step_type": "Method", "summary": "Uses DEM simulation", "paper_source": "paper-A"},
            {"step_type": "Result", "summary": "Accuracy improved", "paper_source": "paper-A"},
        ],
    }
    result = _format_structured_knowledge(knowledge)
    assert "Logic Steps:" in result
    assert "Method" in result
    assert "DEM simulation" in result


def test_format_structured_knowledge_claims_with_ids():
    knowledge = {
        "claims": [
            {
                "claim_id": "abc123",
                "text": "DEM outperforms FEM in granular flow",
                "step_type": "Result",
                "confidence": 0.92,
                "paper_source": "paper-A",
            },
        ],
        "logic_steps": [],
    }
    result = _format_structured_knowledge(knowledge)
    assert "Validated Claims:" in result
    assert "[CL:abc123]" in result
    assert "DEM outperforms FEM" in result
    assert "0.92" in result


def test_format_structured_knowledge_skips_claims_without_id():
    knowledge = {
        "claims": [
            {
                "claim_id": "",
                "text": "Untraceable claim",
                "step_type": "Result",
                "paper_source": "paper-A",
            },
        ],
        "logic_steps": [],
    }
    assert _format_structured_knowledge(knowledge) == ""


def test_format_structured_knowledge_truncates_long_text():
    long_text = "x" * 500
    knowledge = {
        "claims": [
            {"claim_id": "abc123", "text": long_text, "step_type": "Result", "paper_source": "p1"},
        ],
        "logic_steps": [
            {"step_type": "Method", "summary": long_text, "paper_source": "p1"},
        ],
    }
    result = _format_structured_knowledge(knowledge)
    assert "..." in result
    assert "x" * 320 not in result


def test_format_structured_knowledge_combined():
    knowledge = {
        "claims": [
            {"claim_id": "c1", "text": "Claim text", "step_type": "Method",
             "confidence": 0.8, "paper_source": "p1"},
        ],
        "logic_steps": [
            {"step_type": "Background", "summary": "Context info", "paper_source": "p1"},
        ],
    }
    result = _format_structured_knowledge(knowledge)
    assert "Logic Steps:" in result
    assert "Validated Claims:" in result


def test_build_system_prompt_mentions_claims():
    """System prompt should instruct LLM to reference claim IDs."""
    prompt = _build_system_prompt()
    assert "[CL:" in prompt
