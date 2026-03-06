from __future__ import annotations

import json
import pytest


def test_batch_pagination_calls_llm_in_chunks(monkeypatch):
    """With batch_size=3 and 7 cites, LLM is called 3 times (3+3+1)."""
    from app.llm import citation_purpose as cp

    llm_calls: list[list] = []

    def _fake_call_json(system, user):
        # Extract cites from user message
        input_json_str = user.split("Input JSON:\n")[1].split("\n\n")[0]
        batch_ids = [c["cited_paper_id"] for c in json.loads(input_json_str)["cites"]]
        llm_calls.append(batch_ids)
        return {
            "cites": [
                {"cited_paper_id": bid, "labels": ["Survey"], "scores": [0.9]}
                for bid in batch_ids
            ]
        }

    monkeypatch.setattr(cp, "call_json", _fake_call_json)

    cites = [
        {
            "cited_paper_id": f"doi:10.{i}",
            "cited_title": f"Paper {i}",
            "cited_doi": f"10.{i}",
            "contexts": [],
        }
        for i in range(7)
    ]
    result = cp.classify_citation_purposes_batch(
        citing_title="Test Paper",
        cites=cites,
        batch_size=3,
    )

    assert len(llm_calls) == 3, f"Expected 3 LLM calls, got {len(llm_calls)}"
    assert len(llm_calls[0]) == 3
    assert len(llm_calls[1]) == 3
    assert len(llm_calls[2]) == 1
    assert len(result["by_id"]) == 7
    assert isinstance(result["raw"], list), "raw should be a list with pagination"


def test_batch_pagination_single_page(monkeypatch):
    """With 2 cites and batch_size=12, LLM is called exactly once."""
    from app.llm import citation_purpose as cp

    llm_calls: list[int] = []

    def _fake_call_json(system, user):
        input_json_str = user.split("Input JSON:\n")[1].split("\n\n")[0]
        n = len(json.loads(input_json_str)["cites"])
        llm_calls.append(n)
        return {
            "cites": [
                {"cited_paper_id": f"doi:10.{i}", "labels": ["Background"], "scores": [0.4]}
                for i in range(n)
            ]
        }

    monkeypatch.setattr(cp, "call_json", _fake_call_json)

    cites = [
        {"cited_paper_id": f"doi:10.{i}", "cited_title": "", "cited_doi": "", "contexts": []}
        for i in range(2)
    ]
    result = cp.classify_citation_purposes_batch("T", cites, batch_size=12)
    assert len(llm_calls) == 1
    assert len(result["by_id"]) == 2


def test_empty_llm_response_returns_unknown(monkeypatch):
    """When LLM returns empty cites list, missing entry is absent from by_id."""
    from app.llm import citation_purpose as cp

    monkeypatch.setattr(cp, "call_json", lambda s, u: {"cites": []})

    cites = [{"cited_paper_id": "doi:10.1234", "cited_title": "P", "cited_doi": "10.1234", "contexts": []}]
    result = cp.classify_citation_purposes_batch("Test", cites)
    # Missing entry — caller in rebuild.py applies Unknown fallback
    assert "doi:10.1234" not in result["by_id"]


def test_invalid_labels_filtered_to_unknown(monkeypatch):
    """When all labels are invalid (not in PURPOSE_LABELS), fallback is 'Unknown'."""
    from app.llm import citation_purpose as cp

    monkeypatch.setattr(
        cp,
        "call_json",
        lambda s, u: {
            "cites": [{"cited_paper_id": "doi:10.1234", "labels": ["INVALID"], "scores": [0.9]}]
        },
    )
    cites = [{"cited_paper_id": "doi:10.1234", "cited_title": "P", "cited_doi": "10.1234", "contexts": []}]
    result = cp.classify_citation_purposes_batch("Test", cites)
    entry = result["by_id"]["doi:10.1234"]
    assert entry["labels"] == ["Unknown"]


def test_batch_size_zero_raises_value_error():
    """batch_size=0 should raise ValueError before any LLM call."""
    from app.llm import citation_purpose as cp

    with pytest.raises(ValueError, match="batch_size"):
        cp.classify_citation_purposes_batch("Test", [], batch_size=0)


def test_batch_size_negative_raises_value_error():
    """batch_size=-5 should raise ValueError before any LLM call."""
    from app.llm import citation_purpose as cp

    with pytest.raises(ValueError, match="batch_size"):
        cp.classify_citation_purposes_batch("Test", [], batch_size=-5)
