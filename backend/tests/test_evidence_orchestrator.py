from app.rag.evidence_orchestrator import merge_evidence


def test_merge_evidence_deduplicates_and_keeps_rank_order():
    merged = merge_evidence(
        faiss=[{"chunk_id": "c1"}, {"chunk_id": "c2"}],
        lexical=[{"chunk_id": "c2"}, {"chunk_id": "c3"}],
        k=3,
    )
    assert [x["chunk_id"] for x in merged] == ["c2", "c1", "c3"]
