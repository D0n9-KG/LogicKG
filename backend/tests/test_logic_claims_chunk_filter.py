from __future__ import annotations

import unittest
from unittest.mock import patch

from app.ingest.models import Chunk, DocumentIR, MdSpan, PaperDraft
from app.llm.logic_claims_v2 import add_logic_step_evidence, extract_logic_and_claims_v2


def _doc_with_reference_chunk() -> DocumentIR:
    paper = PaperDraft(
        paper_source="paperA",
        md_path="C:/tmp/paperA/source.md",
        title="Paper A",
        title_alt=None,
        authors=["Alice"],
        doi="10.1000/papera",
        year=2024,
    )
    chunks = [
        Chunk(
            chunk_id="c1",
            paper_source="paperA",
            md_path="C:/tmp/paperA/source.md",
            span=MdSpan(start_line=10, end_line=12),
            section="Method",
            kind="block",
            text="Our method uses finite elements and improves stability.",
        ),
        Chunk(
            chunk_id="c2",
            paper_source="paperA",
            md_path="C:/tmp/paperA/source.md",
            span=MdSpan(start_line=90, end_line=92),
            section="References",
            kind="block",
            text="[1] Method method method method details in bibliography only.",
        ),
    ]
    return DocumentIR(paper=paper, chunks=chunks, references=[], citations=[])


class LogicClaimsChunkFilterTests(unittest.TestCase):
    def test_add_logic_step_evidence_skips_reference_section_by_default(self) -> None:
        doc = _doc_with_reference_chunk()
        schema = {"rules": {"logic_evidence_min": 1, "logic_evidence_max": 1}}
        logic = {"Method": {"summary": "Method improves stability.", "confidence": 0.8}}

        out = add_logic_step_evidence(doc=doc, schema=schema, logic=logic)
        self.assertEqual(out["Method"]["evidence_chunk_ids"], ["c1"])

    def test_extract_logic_prompt_body_skips_reference_section_by_default(self) -> None:
        doc = _doc_with_reference_chunk()
        schema = {
            "steps": [{"id": "Method", "enabled": True}],
            "claim_kinds": [{"id": "Method", "enabled": True}],
            "rules": {
                "claims_per_paper_min": 1,
                "claims_per_paper_max": 2,
                "phase1_doc_chars_max": 2000,
            },
            "prompts": {},
        }

        with patch("app.llm.logic_claims_v2.call_validated_json", side_effect=Exception("skip")), \
             patch("app.llm.logic_claims_v2.call_json", return_value={"logic": {}, "claims": []}) as mocked:
            extract_logic_and_claims_v2(doc=doc, paper_id="doi:10.1000/papera", schema=schema)

        user_prompt = str(mocked.call_args[0][1])
        self.assertIn("Our method uses finite elements", user_prompt)
        self.assertNotIn("bibliography only", user_prompt)


if __name__ == "__main__":
    unittest.main()
