from app.rag.fusion_retrieval import (
    format_fusion_evidence_block,
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
