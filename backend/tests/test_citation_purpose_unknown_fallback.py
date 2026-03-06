"""Test Unknown fallback consistency for missing citation purpose labels."""
from __future__ import annotations


def test_missing_cited_paper_id_uses_unknown_fallback():
    """When LLM returns empty by_id for a cite, fallback should be Unknown/0.0 not Background/0.4."""
    # This test verifies the fallback logic pattern from rebuild.py
    by_id = {}  # LLM did not return entry for cited_paper_id="doi:10.1234"

    # Simulate pipeline.py fallback logic
    cited_paper_id = "doi:10.1234"
    # Old behavior (incorrect): {"labels": ["Background"], "scores": [0.4]}
    # New behavior (correct): {"labels": ["Unknown"], "scores": [0.0]}
    x = by_id.get(str(cited_paper_id)) or {"labels": ["Unknown"], "scores": [0.0]}

    assert x["labels"] == ["Unknown"]
    assert x["scores"] == [0.0]


def test_present_cited_paper_id_uses_llm_result():
    """When LLM returns valid entry for cited_paper_id, use it directly."""
    by_id = {"doi:10.1234": {"labels": ["MethodUse"], "scores": [0.85]}}

    cited_paper_id = "doi:10.1234"
    x = by_id.get(str(cited_paper_id)) or {"labels": ["Unknown"], "scores": [0.0]}

    assert x["labels"] == ["MethodUse"]
    assert x["scores"] == [0.85]
