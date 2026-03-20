from __future__ import annotations

from app.vector import faiss_store


def test_prepare_rows_for_faiss_splits_oversized_text_and_preserves_chunk_metadata() -> None:
    oversized = ("A" * 4200) + "\n\n" + ("B" * 4200)
    rows = [
        {
            "text": oversized,
            "chunk_id": "chunk-oversized",
            "paper_source": "paper-A",
            "md_path": "runs/paper-A/content.md",
        }
    ]

    texts, metadatas = faiss_store._prepare_rows_for_faiss(  # type: ignore[attr-defined]
        rows,
        text_key="text",
        metadata_keys=["chunk_id", "paper_source", "md_path"],
        max_chars=6000,
        overlap_chars=0,
    )

    assert len(texts) == 2
    assert all(len(text) <= 6000 for text in texts)
    assert [md["chunk_id"] for md in metadatas] == ["chunk-oversized", "chunk-oversized"]
    assert [md["paper_source"] for md in metadatas] == ["paper-A", "paper-A"]
    assert [md["faiss_segment_index"] for md in metadatas] == [0, 1]
    assert all(md["faiss_segment_count"] == 2 for md in metadatas)


def test_prepare_rows_for_faiss_keeps_small_rows_unchanged() -> None:
    rows = [
        {
            "text": "Finite element methods improve stability.",
            "chunk_id": "chunk-small",
            "paper_source": "paper-B",
        }
    ]

    texts, metadatas = faiss_store._prepare_rows_for_faiss(  # type: ignore[attr-defined]
        rows,
        text_key="text",
        metadata_keys=["chunk_id", "paper_source"],
        max_chars=6000,
        overlap_chars=0,
    )

    assert texts == ["Finite element methods improve stability."]
    assert metadatas == [{"chunk_id": "chunk-small", "paper_source": "paper-B"}]
