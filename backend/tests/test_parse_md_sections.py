from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.ingest.parse_md import parse_mineru_markdown


class ParseMarkdownSectionsTests(unittest.TestCase):
    def test_sections_are_bound_per_block_not_global(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "paper.md"
            p.write_text(
                "# Intro\n\n"
                "Intro body sentence.\n\n"
                "# Method\n\n"
                "Method body sentence.\n\n"
                "# REFERENCES\n\n"
                "[1] Ref entry.\n",
                encoding="utf-8",
            )
            doc = parse_mineru_markdown(str(p))

        blocks = [c for c in doc.chunks if c.kind == "block"]
        intro_blocks = [c for c in blocks if "Intro body sentence." in c.text]
        method_blocks = [c for c in blocks if "Method body sentence." in c.text]
        self.assertEqual(len(intro_blocks), 1)
        self.assertEqual(len(method_blocks), 1)
        self.assertEqual(intro_blocks[0].section, "Intro")
        self.assertEqual(method_blocks[0].section, "Method")

    def test_reference_section_doi_is_not_promoted_to_paper_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "paper.md"
            p.write_text(
                "# DEM investigation of particle anti-rotation effects on the micromechanical response of granular materials\n\n"
                "Bo Zhou, Runqiu Huang\n\n"
                "Main body paragraph.\n\n"
                "# References\n\n"
                "[1] Example cited paper. doi:10.1061/(ASCE)GT.1943-5606.0000890\n",
                encoding="utf-8",
            )
            doc = parse_mineru_markdown(str(p))

        self.assertIsNone(doc.paper.doi)


if __name__ == "__main__":
    unittest.main()

