"""Tests for structured retrieval and grounding helpers."""
from __future__ import annotations

import importlib


def _structured_module():
    return importlib.import_module("app.rag.structured_retrieval")


def test_direct_structured_retrievers_return_logic_claim_and_proposition_hits(monkeypatch) -> None:
    structured = _structured_module()

    def _fake_search(corpus: str, query: str, k: int, allowed_sources=None):
        base = {
            "logic_steps": [{"kind": "logic_step", "id": "ls-1", "text": "Uses finite element discretization.", "score": 0.81}],
            "claims": [{"kind": "claim", "id": "cl-1", "text": "FEM improves stability.", "score": 0.82}],
            "propositions": [{"kind": "proposition", "id": "pr-1", "text": "Finite element discretization stabilizes PDE solving.", "score": 0.79}],
        }
        return list(base[corpus])[:k]

    monkeypatch.setattr(structured, "_search_corpus", _fake_search, raising=False)

    logic_hits = structured.retrieve_logic_steps("finite element method", k=2)
    claim_hits = structured.retrieve_claims("finite element method", k=2)
    proposition_hits = structured.retrieve_propositions("finite element method", k=2)

    assert logic_hits[0]["kind"] == "logic_step"
    assert claim_hits[0]["kind"] == "claim"
    assert proposition_hits[0]["kind"] == "proposition"


def test_foundational_plan_prefers_textbook_and_proposition_hits_before_chunks() -> None:
    structured = _structured_module()

    ranked = structured.fuse_retrieval_channels(
        retrieval_plan="textbook_first_then_paper",
        question="What are the assumptions of finite element method?",
        chunk_hits=[{"kind": "chunk", "id": "c1", "text": "This paper applies FEM.", "score": 0.91}],
        logic_hits=[{"kind": "logic_step", "id": "ls-1", "text": "Uses FEM.", "score": 0.84}],
        claim_hits=[{"kind": "claim", "id": "cl-1", "text": "FEM improves stability.", "score": 0.83}],
        proposition_hits=[{"kind": "proposition", "id": "pr-1", "text": "Finite element discretization stabilizes PDE solving.", "score": 0.79}],
        textbook_hits=[{"kind": "textbook", "id": "tb-1", "text": "Finite element method definition and assumptions.", "score": 0.78}],
        k=4,
    )

    assert [row["kind"] for row in ranked[:2]] == ["textbook", "proposition"]


def test_paper_detail_plan_prefers_claim_and_logic_hits_from_target_paper() -> None:
    structured = _structured_module()

    ranked = structured.fuse_retrieval_channels(
        retrieval_plan="claim_first",
        question="What method and results does this paper report?",
        chunk_hits=[{"kind": "chunk", "id": "c1", "text": "Chunk summary.", "score": 0.92, "paper_source": "paper-A"}],
        logic_hits=[{"kind": "logic_step", "id": "ls-1", "text": "Method: uses FEM.", "score": 0.84, "paper_source": "paper-A"}],
        claim_hits=[{"kind": "claim", "id": "cl-1", "text": "Result: FEM improves stability.", "score": 0.88, "paper_source": "paper-A"}],
        proposition_hits=[{"kind": "proposition", "id": "pr-1", "text": "Canonical proposition.", "score": 0.75, "paper_source": "paper-B"}],
        textbook_hits=[{"kind": "textbook", "id": "tb-1", "text": "General FEM background.", "score": 0.81}],
        k=4,
    )

    assert [row["kind"] for row in ranked[:2]] == ["claim", "logic_step"]
    assert all(row.get("paper_source") == "paper-A" for row in ranked[:2])


def test_structured_rows_preserve_provenance_and_grounding_fields() -> None:
    structured = _structured_module()

    rows = structured.normalize_structured_rows(
        [
            {
                "kind": "proposition",
                "id": "pr-1",
                "text": "Finite element discretization stabilizes PDE solving.",
                "score": 0.79,
                "source_kind": "claim",
                "source_id": "cl-1",
                "quote": "Finite element method discretizes the domain.",
                "chunk_id": "c1",
                "start_line": 12,
                "end_line": 14,
            },
            {
                "kind": "proposition",
                "id": "pr-2",
                "text": "Textbook proposition.",
                "score": 0.76,
                "source_kind": "textbook_entity",
                "source_id": "ent-7",
                "quote": "The element basis interpolates the field variable.",
                "chapter_id": "tb:1:ch001",
            },
        ]
    )

    assert rows[0]["source_kind"] == "claim"
    assert rows[0]["source_id"] == "cl-1"
    assert rows[0]["quote"] == "Finite element method discretizes the domain."
    assert rows[0]["chunk_id"] == "c1"
    assert rows[0]["start_line"] == 12
    assert rows[0]["end_line"] == 14
    assert rows[1]["source_kind"] == "textbook_entity"
    assert rows[1]["chapter_id"] == "tb:1:ch001"
