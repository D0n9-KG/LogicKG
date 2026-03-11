"""Tests for structured retrieval and grounding helpers."""
from __future__ import annotations

import importlib


def _structured_module():
    return importlib.import_module("app.rag.structured_retrieval")


def test_direct_structured_retrievers_return_logic_claim_and_community_hits(monkeypatch) -> None:
    structured = _structured_module()

    def _fake_search(corpus: str, query: str, k: int, allowed_sources=None):
        del query, allowed_sources
        base = {
            "logic_steps": [{"kind": "logic_step", "id": "ls-1", "text": "Uses finite element discretization.", "score": 0.81}],
            "claims": [{"kind": "claim", "id": "cl-1", "text": "FEM improves stability.", "score": 0.82}],
            "communities": [
                {
                    "kind": "community",
                    "community_id": "gc:demo",
                    "text": "Finite element stability cluster.",
                    "member_ids": ["cl-1", "ke-1"],
                    "member_kinds": ["Claim", "KnowledgeEntity"],
                    "keyword_texts": ["finite element", "stability"],
                    "score": 0.79,
                }
            ],
        }
        return list(base[corpus])[:k]

    monkeypatch.setattr(structured, "_search_corpus", _fake_search, raising=False)

    logic_hits = structured.retrieve_logic_steps("finite element method", k=2)
    claim_hits = structured.retrieve_claims("finite element method", k=2)
    community_hits = structured.retrieve_communities("finite element method", k=2)

    assert logic_hits[0]["kind"] == "logic_step"
    assert claim_hits[0]["kind"] == "claim"
    assert community_hits[0]["kind"] == "community"


def test_direct_structured_retrievers_return_community_hits(monkeypatch) -> None:
    structured = _structured_module()
    assert hasattr(structured, "retrieve_communities"), "Expected retrieve_communities() to be implemented."

    def _fake_search(corpus: str, query: str, k: int, allowed_sources=None):
        del query, allowed_sources
        if corpus == "communities":
            return [
                {
                    "kind": "community",
                    "source_id": "gc:demo",
                    "community_id": "gc:demo",
                    "text": "Finite element stability cluster.",
                    "member_ids": ["cl-1", "ke-1"],
                    "member_kinds": ["Claim", "KnowledgeEntity"],
                    "keyword_texts": ["finite element", "stability"],
                    "score": 0.88,
                }
            ][:k]
        return []

    monkeypatch.setattr(structured, "_search_corpus", _fake_search, raising=False)

    community_hits = structured.retrieve_communities("finite element stability", k=2)

    assert community_hits == [
        {
            "kind": "community",
            "source_id": "gc:demo",
            "community_id": "gc:demo",
            "id": "gc:demo",
            "text": "Finite element stability cluster.",
            "member_ids": ["cl-1", "ke-1"],
            "member_kinds": ["Claim", "KnowledgeEntity"],
            "keyword_texts": ["finite element", "stability"],
            "score": 0.88,
        }
    ]


def test_normalize_structured_rows_preserves_community_membership_metadata() -> None:
    structured = _structured_module()

    rows = structured.normalize_structured_rows(
        [
            {
                "kind": "community",
                "community_id": "gc:demo",
                "text": "Finite element stability cluster.",
                "member_ids": ["cl-1", "ke-1"],
                "member_kinds": ["Claim", "KnowledgeEntity"],
                "keyword_texts": ["finite element", "stability"],
                "score": 0.88,
            }
        ]
    )

    assert rows == [
        {
            "kind": "community",
            "source_id": "gc:demo",
            "community_id": "gc:demo",
            "id": "gc:demo",
            "text": "Finite element stability cluster.",
            "member_ids": ["cl-1", "ke-1"],
            "member_kinds": ["Claim", "KnowledgeEntity"],
            "keyword_texts": ["finite element", "stability"],
            "score": 0.88,
        }
    ]


def test_paper_scoped_community_retrieval_excludes_blank_and_non_matching_sources(monkeypatch) -> None:
    structured = _structured_module()

    monkeypatch.setattr(
        structured,
        "_load_corpus_rows",
        lambda corpus: [
            {"kind": "community", "community_id": "gc:blank", "text": "Blank source textbook community."},
            {"kind": "community", "community_id": "gc:other", "text": "Other paper community.", "paper_source": "paper-B"},
            {"kind": "community", "community_id": "gc:allowed", "text": "Allowed paper community.", "paper_source": "paper-A"},
        ]
        if corpus == "communities"
        else [],
        raising=False,
    )

    community_hits = structured.retrieve_communities(
        "finite element method",
        k=4,
        allowed_sources={"paper-A"},
    )

    assert [row["id"] for row in community_hits] == ["gc:allowed"]


def test_foundational_plan_prefers_textbook_and_community_hits_before_chunks() -> None:
    structured = _structured_module()

    ranked = structured.fuse_retrieval_channels(
        retrieval_plan="textbook_first_then_paper",
        question="What are the assumptions of finite element method?",
        chunk_hits=[{"kind": "chunk", "id": "c1", "text": "This paper applies FEM.", "score": 0.91}],
        logic_hits=[{"kind": "logic_step", "id": "ls-1", "text": "Uses FEM.", "score": 0.84}],
        claim_hits=[{"kind": "claim", "id": "cl-1", "text": "FEM improves stability.", "score": 0.83}],
        community_hits=[
            {
                "kind": "community",
                "community_id": "gc:demo",
                "id": "gc:demo",
                "text": "Finite element stability cluster.",
                "score": 0.79,
            }
        ],
        textbook_hits=[{"kind": "textbook", "id": "tb-1", "text": "Finite element method definition and assumptions.", "score": 0.78}],
        k=4,
    )

    assert [row["kind"] for row in ranked[:2]] == ["textbook", "community"]


def test_paper_detail_plan_prefers_claim_and_logic_hits_from_target_paper() -> None:
    structured = _structured_module()

    ranked = structured.fuse_retrieval_channels(
        retrieval_plan="claim_first",
        question="What method and results does this paper report?",
        chunk_hits=[{"kind": "chunk", "id": "c1", "text": "Chunk summary.", "score": 0.92, "paper_source": "paper-A"}],
        logic_hits=[{"kind": "logic_step", "id": "ls-1", "text": "Method: uses FEM.", "score": 0.84, "paper_source": "paper-A"}],
        claim_hits=[{"kind": "claim", "id": "cl-1", "text": "Result: FEM improves stability.", "score": 0.88, "paper_source": "paper-A"}],
        community_hits=[
            {
                "kind": "community",
                "community_id": "gc:paper-b",
                "id": "gc:paper-b",
                "text": "Canonical community.",
                "score": 0.75,
                "paper_source": "paper-B",
            }
        ],
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
                "kind": "community",
                "community_id": "gc:demo",
                "text": "Finite element stability cluster.",
                "score": 0.79,
                "member_ids": ["cl-1", "ke-1"],
                "member_kinds": ["Claim", "KnowledgeEntity"],
                "keyword_texts": ["finite element", "stability"],
                "paper_source": "paper-A",
            },
            {
                "kind": "claim",
                "id": "cl-1",
                "text": "Finite element discretization stabilizes PDE solving.",
                "score": 0.76,
                "community_id": "gc:demo",
                "quote": "The finite element domain is discretized before solving.",
                "chunk_id": "c1",
                "start_line": 12,
                "end_line": 14,
                "evidence_event_id": "ev-1",
                "evidence_event_type": "SUPPORTS",
            },
        ]
    )

    assert rows[0]["community_id"] == "gc:demo"
    assert rows[0]["member_ids"] == ["cl-1", "ke-1"]
    assert rows[0]["keyword_texts"] == ["finite element", "stability"]
    assert rows[1]["community_id"] == "gc:demo"
    assert rows[1]["quote"] == "The finite element domain is discretized before solving."
    assert rows[1]["chunk_id"] == "c1"
    assert rows[1]["start_line"] == 12
    assert rows[1]["end_line"] == 14
    assert rows[1]["evidence_event_id"] == "ev-1"
    assert rows[1]["evidence_event_type"] == "SUPPORTS"


def test_retrieve_communities_prefers_faiss_hits_and_preserves_membership_fields(monkeypatch) -> None:
    structured = _structured_module()

    class _Doc:
        def __init__(self) -> None:
            self.page_content = "Finite element discretization stabilizes PDE solving."
            self.metadata = {
                "kind": "community",
                "source_id": "gc:demo",
                "community_id": "gc:demo",
                "paper_source": "paper-A",
                "paper_id": "doi:10.1000/example",
                "member_ids": ["cl-1", "ke-1"],
                "member_kinds": ["Claim", "KnowledgeEntity"],
                "keyword_texts": ["finite element", "stability"],
            }

    class _FakeStore:
        def similarity_search_with_score(self, query, k=0):
            return [(_Doc(), 0.23)]

    monkeypatch.setattr(structured, "_corpus_faiss_dir", lambda corpus: f"fake/{corpus}", raising=False)
    monkeypatch.setattr(structured, "load_faiss", lambda path: _FakeStore(), raising=False)
    monkeypatch.setattr(
        structured,
        "_load_corpus_rows",
        lambda corpus: (_ for _ in ()).throw(AssertionError("lexical fallback should not run when FAISS is available")),
        raising=False,
    )

    hits = structured.retrieve_communities("finite element method", k=2)

    assert hits == [
        {
            "kind": "community",
            "source_id": "gc:demo",
            "community_id": "gc:demo",
            "id": "gc:demo",
            "text": "Finite element discretization stabilizes PDE solving.",
            "score": 0.23,
            "paper_source": "paper-A",
            "paper_id": "doi:10.1000/example",
            "member_ids": ["cl-1", "ke-1"],
            "member_kinds": ["Claim", "KnowledgeEntity"],
            "keyword_texts": ["finite element", "stability"],
        }
    ]


def test_retrieve_claims_calls_faiss_then_falls_back_to_lexical_rows(monkeypatch) -> None:
    structured = _structured_module()
    attempts = {"faiss": 0}

    def _missing_faiss(path: str):
        attempts["faiss"] += 1
        raise FileNotFoundError(path)

    monkeypatch.setattr(structured, "_corpus_faiss_dir", lambda corpus: f"fake/{corpus}", raising=False)
    monkeypatch.setattr(structured, "load_faiss", _missing_faiss, raising=False)
    monkeypatch.setattr(
        structured,
        "_load_corpus_rows",
        lambda corpus: [
            {
                "kind": "claim",
                "source_id": "cl-1",
                "text": "FEM improves stability.",
                "paper_source": "paper-A",
                "paper_id": "doi:10.1000/example",
                "community_id": "gc:demo",
                "evidence_quote": "Finite element method discretizes the domain.",
            }
        ]
        if corpus == "claims"
        else [],
        raising=False,
    )

    hits = structured.retrieve_claims("finite element stability", k=2)

    assert attempts["faiss"] == 1
    assert hits == [
        {
            "kind": "claim",
            "source_id": "cl-1",
            "id": "cl-1",
            "text": "FEM improves stability.",
            "paper_source": "paper-A",
            "paper_id": "doi:10.1000/example",
            "community_id": "gc:demo",
            "evidence_quote": "Finite element method discretizes the domain.",
            "score": 0.6666666666666666,
        }
    ]


def test_corpus_faiss_dir_prefers_global_corpus_when_present(tmp_path, monkeypatch) -> None:
    structured = _structured_module()
    global_root = tmp_path / "storage" / "faiss"
    run_root = tmp_path / "runs" / "run-1" / "faiss"
    (global_root / "claims").mkdir(parents=True)
    (run_root / "claims").mkdir(parents=True)
    latest = tmp_path / "runs" / "LATEST"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text("run-1", encoding="utf-8")

    monkeypatch.setattr(structured, "_storage_dir", lambda: tmp_path / "storage", raising=False)
    monkeypatch.setattr(structured, "_runs_dir", lambda: tmp_path / "runs", raising=False)

    assert structured._corpus_faiss_dir("claims") == str(global_root / "claims")


def test_corpus_faiss_dir_falls_back_to_latest_run_local_corpus(tmp_path, monkeypatch) -> None:
    structured = _structured_module()
    global_root = tmp_path / "storage" / "faiss"
    run_root = tmp_path / "runs" / "run-1" / "faiss"
    (global_root / "chunks").mkdir(parents=True)
    (run_root / "claims").mkdir(parents=True)
    latest = tmp_path / "runs" / "LATEST"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text("run-1", encoding="utf-8")

    monkeypatch.setattr(structured, "_storage_dir", lambda: tmp_path / "storage", raising=False)
    monkeypatch.setattr(structured, "_runs_dir", lambda: tmp_path / "runs", raising=False)

    assert structured._corpus_faiss_dir("claims") == str(run_root / "claims")
