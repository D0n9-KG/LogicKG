from __future__ import annotations

from pathlib import Path

from app.ingest import rebuild as rebuild_mod


class _FakeNeo4jClient:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        return False

    def list_chunks_for_faiss(self, limit=200000):  # noqa: ARG002
        return [
            {
                "chunk_id": "chunk-1",
                "paper_source": "paper-A",
                "md_path": "runs/paper-A/content.md",
                "start_line": 1,
                "end_line": 2,
                "section": "Intro",
                "kind": "paragraph",
                "text": "Finite element methods improve numerical stability.",
            }
        ]

    def list_logic_step_structured_rows(self, limit=50000):  # noqa: ARG002
        return [
            {
                "kind": "logic_step",
                "source_id": "ls-1",
                "paper_id": "doi:10.1000/example",
                "paper_source": "paper-A",
                "step_type": "Method",
                "evidence_chunk_ids": ["chunk-1"],
                "evidence_quote": "Finite element methods improve numerical stability.",
                "text": "Method step about FEM stability.",
            }
        ]

    def list_claim_structured_rows(self, limit=50000):  # noqa: ARG002
        return [
            {
                "kind": "claim",
                "source_id": "cl-1",
                "paper_id": "doi:10.1000/example",
                "paper_source": "paper-A",
                "step_type": "Result",
                "confidence": 0.91,
                "evidence_chunk_ids": ["chunk-1"],
                "evidence_quote": "Finite element methods improve numerical stability.",
                "text": "Finite element methods improve numerical stability.",
            }
        ]

    def list_global_community_rows(self, limit=50000):  # noqa: ARG002
        return [
            {
                "community_id": "gc:demo",
                "title": "Finite element stability",
                "summary": "Claims and textbook entities about FEM stability.",
                "keywords": ["finite element", "stability"],
            }
        ]

    def list_global_community_members(self, community_id: str, limit=200):  # noqa: ARG002
        assert community_id == "gc:demo"
        return [
            {"member_id": "cl-1", "member_kind": "Claim", "text": "FEM improves stability."},
            {"member_id": "ke-1", "member_kind": "KnowledgeEntity", "text": "Finite Element Method"},
        ]

    def list_proposition_structured_rows(self, limit=50000):  # noqa: ARG002
        raise AssertionError("rebuild_global_faiss should not export proposition corpora")


def test_rebuild_global_faiss_keeps_only_community_corpora_and_removes_stale_proposition_exports(monkeypatch, tmp_path) -> None:
    fake_client = _FakeNeo4jClient()
    built_row_corpora: list[tuple[str, list[dict]]] = []

    monkeypatch.setattr(rebuild_mod, "Neo4jClient", lambda *args, **kwargs: fake_client)  # noqa: ARG005
    monkeypatch.setattr(rebuild_mod, "_storage_dir", lambda: tmp_path)
    monkeypatch.setattr(
        rebuild_mod,
        "build_faiss_for_chunks",
        lambda chunks, out_dir: {"out_dir": str(out_dir), "chunk_count": len(chunks)},
    )
    monkeypatch.setattr(
        rebuild_mod,
        "build_faiss_for_rows",
        lambda rows, out_dir, **kwargs: built_row_corpora.append((str(out_dir), list(rows))) or {  # noqa: ARG005
            "out_dir": str(out_dir),
            "row_count": len(list(rows)),
        },
    )

    stale_dir = tmp_path / "faiss" / "propositions"
    stale_dir.mkdir(parents=True)
    stale_file = stale_dir / "index.faiss"
    stale_file.write_text("stale proposition index", encoding="utf-8")
    assert stale_file.exists()

    result = rebuild_mod.rebuild_global_faiss()

    assert "propositions" not in result["faiss"]["corpora"]
    assert not any("propositions" in out_dir for out_dir, _ in built_row_corpora)
    community_corpus = next(rows for out_dir, rows in built_row_corpora if out_dir.endswith("communities"))
    assert community_corpus == [
        {
            "community_id": "gc:demo",
            "title": "Finite element stability",
            "summary": "Claims and textbook entities about FEM stability.",
            "keywords": ["finite element", "stability"],
            "kind": "community",
            "source_id": "gc:demo",
            "id": "gc:demo",
            "member_ids": ["cl-1", "ke-1"],
            "member_kinds": ["Claim", "KnowledgeEntity"],
            "keyword_texts": ["finite element", "stability"],
            "text": (
                "Finite element stability\n"
                "Claims and textbook entities about FEM stability.\n"
                "keywords: finite element, stability"
            ),
        }
    ]
    assert not stale_dir.exists()
