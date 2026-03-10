from app.rag.fusion_retrieval import (
    format_fusion_evidence_block,
    fusion_rows_to_structured_hits,
    rank_fusion_basics,
)


def test_rank_fusion_basics_includes_textbook_fundamental_for_section_question() -> None:
    rows = [
        {
            "paper_source": "p1",
            "step_type": "Method",
            "entity_name": "Finite Element Method",
            "entity_type": "method",
            "description": "A numerical method for PDE discretization.",
            "score": 0.83,
            "evidence_quote": "Finite element method discretizes structure.",
        },
        {
            "paper_source": "p1",
            "step_type": "Background",
            "entity_name": "Industrial Revolution",
            "entity_type": "history",
            "description": "Historical period.",
            "score": 0.95,
            "evidence_quote": "Historical background.",
        },
    ]
    ranked = rank_fusion_basics("What is the method used in this paper?", rows, k=2)

    assert ranked
    assert ranked[0]["entity_name"] == "Finite Element Method"


def test_format_fusion_evidence_block_is_nonempty_for_ranked_rows() -> None:
    ranked = [
        {
            "paper_source": "p1",
            "step_type": "Result",
            "entity_name": "Natural Frequency",
            "entity_type": "theory",
            "score": 0.88,
            "evidence_quote": "Natural frequency increases with stiffness.",
        }
    ]
    block = format_fusion_evidence_block(ranked)
    assert "Textbook Fundamentals" in block
    assert "Natural Frequency" in block


def test_fusion_rows_to_structured_hits_preserves_textbook_metadata() -> None:
    hits = fusion_rows_to_structured_hits(
        [
            {
                "paper_source": "p1",
                "paper_id": "doi:10.1000/example",
                "logic_step_id": "ls-1",
                "step_type": "Method",
                "entity_id": "ent-1",
                "entity_name": "Finite Element Method",
                "entity_type": "method",
                "description": "A numerical method for PDE discretization.",
                "rank_score": 0.91,
                "score": 0.83,
                "textbook_id": "tb:1",
                "chapter_id": "tb:1:ch001",
            }
        ]
    )

    assert len(hits) == 1
    assert hits[0]["kind"] == "textbook"
    assert hits[0]["source_id"] == "ent-1"
    assert hits[0]["id"] == "ent-1"
    assert hits[0]["text"] == "Finite Element Method: A numerical method for PDE discretization."
    assert hits[0]["score"] == 0.91
    assert hits[0]["paper_source"] == "p1"
    assert hits[0]["paper_id"] == "doi:10.1000/example"
    assert hits[0]["source_kind"] == "textbook_entity"
    assert hits[0]["source_ref_id"] == "ent-1"
    assert hits[0]["textbook_id"] == "tb:1"
    assert hits[0]["chapter_id"] == "tb:1:ch001"


def test_fusion_rows_to_structured_hits_preserves_fusion_provenance() -> None:
    hits = fusion_rows_to_structured_hits(
        [
            {
                "paper_source": "p1",
                "paper_id": "doi:10.1000/example",
                "logic_step_id": "ls-1",
                "step_type": "Method",
                "entity_id": "ent-1",
                "entity_name": "Finite Element Method",
                "entity_type": "method",
                "description": "A numerical method for PDE discretization.",
                "rank_score": 0.91,
                "score": 0.83,
                "textbook_id": "tb:1",
                "chapter_id": "tb:1:ch001",
                "source_chapter_id": "tb:1:ch001",
                "reasons": ["coverage=1.0", "type=method"],
                "evidence_chunk_ids": ["c1", "c2"],
                "source_chunk_id": "c1",
                "evidence_quote": "Finite element method discretizes structure.",
            }
        ]
    )

    assert hits[0]["logic_step_id"] == "ls-1"
    assert hits[0]["source_chapter_id"] == "tb:1:ch001"
    assert hits[0]["reasons"] == ["coverage=1.0", "type=method"]
    assert hits[0]["evidence_chunk_ids"] == ["c1", "c2"]
    assert hits[0]["source_chunk_id"] == "c1"
    assert hits[0]["evidence_quote"] == "Finite element method discretizes structure."
