from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingest.models import DocumentIR, PaperDraft, ReferenceEntry
from app.llm.reference_recovery import recover_references_with_agent


def _doc(md_path: str, refs: list[ReferenceEntry] | None = None) -> DocumentIR:
    paper = PaperDraft(
        paper_source="p1",
        md_path=md_path,
        title="A Test Paper",
        title_alt=None,
        authors=["Alice", "Bob"],
        doi="10.1234/test",
        year=2024,
    )
    return DocumentIR(paper=paper, chunks=[], references=refs or [], citations=[])


class ReferenceRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.md_path = str(Path(self.tmp.name) / "paper.md")
        Path(self.md_path).write_text(
            "# Title\n\nSome body text.\n\n# REFERENCES\n1. Foo et al. Test Journal (2020)\n2. Bar et al. Demo Journal (2021)\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_attempts_recovery_when_existing_refs_below_dynamic_threshold(self) -> None:
        doc = _doc(
            self.md_path,
            refs=[ReferenceEntry(paper_source="p1", md_path=self.md_path, ref_num=1, raw="Foo 2020")],
        )
        payload = {"references": [{"raw": "[1] Foo et al. Test Journal (2020)"}]}
        with patch("app.llm.reference_recovery.call_json", return_value=payload) as mocked:
            out, report = recover_references_with_agent(doc, rules={"reference_recovery_enabled": True})
        mocked.assert_called_once()
        self.assertEqual(len(out.references), 1)
        self.assertEqual(report.get("status"), "kept_existing_not_improved")

    def test_skips_when_existing_refs_above_dynamic_threshold(self) -> None:
        doc = _doc(
            self.md_path,
            refs=[
                ReferenceEntry(paper_source="p1", md_path=self.md_path, ref_num=1, raw="Foo 2020"),
                ReferenceEntry(paper_source="p1", md_path=self.md_path, ref_num=2, raw="Bar 2021"),
            ],
        )
        with patch("app.llm.reference_recovery.call_json") as mocked:
            out, report = recover_references_with_agent(
                doc,
                rules={
                    "reference_recovery_enabled": True,
                    "reference_recovery_trigger_max_existing_refs": 1,
                    "reference_recovery_trigger_min_refs": 1,
                    "reference_recovery_trigger_min_refs_per_1k_chars": 0.0,
                },
            )
        mocked.assert_not_called()
        self.assertEqual(len(out.references), 2)
        self.assertEqual(report.get("status"), "skipped_existing_above_dynamic_threshold")

    def test_replaces_existing_refs_when_triggered_and_improved(self) -> None:
        doc = _doc(
            self.md_path,
            refs=[ReferenceEntry(paper_source="p1", md_path=self.md_path, ref_num=1, raw="Foo 2020")],
        )
        payload = {
            "references": [
                {"raw": "[1] Foo et al. Test Journal (2020)"},
                "2. Bar et al. Demo Journal (2021)",
                "3. Baz et al. Another Journal (2022)",
            ]
        }
        with patch("app.llm.reference_recovery.call_json", return_value=payload) as mocked:
            out, report = recover_references_with_agent(
                doc,
                rules={
                    "reference_recovery_enabled": True,
                    "reference_recovery_trigger_max_existing_refs": 1,
                    "reference_recovery_max_refs": 10,
                },
            )
        mocked.assert_called_once()
        self.assertEqual(report.get("status"), "recovered")
        self.assertTrue(bool(report.get("replaced_existing")))
        self.assertEqual(report.get("after_refs"), 3)
        self.assertEqual(len(out.references), 3)

    def test_keeps_existing_refs_when_candidate_not_improved(self) -> None:
        doc = _doc(
            self.md_path,
            refs=[
                ReferenceEntry(paper_source="p1", md_path=self.md_path, ref_num=1, raw="Foo 2020"),
                ReferenceEntry(paper_source="p1", md_path=self.md_path, ref_num=2, raw="Bar 2021"),
            ],
        )
        payload = {"references": [{"raw": "[1] Foo et al. Test Journal (2020)"}]}
        with patch("app.llm.reference_recovery.call_json", return_value=payload) as mocked:
            out, report = recover_references_with_agent(
                doc,
                rules={
                    "reference_recovery_enabled": True,
                    "reference_recovery_trigger_max_existing_refs": 2,
                    "reference_recovery_max_refs": 10,
                },
            )
        mocked.assert_called_once()
        self.assertEqual(report.get("status"), "kept_existing_not_improved")
        self.assertEqual(report.get("after_refs"), 2)
        self.assertEqual(len(out.references), 2)

    def test_skips_when_recovery_disabled(self) -> None:
        doc = _doc(self.md_path, refs=[])
        with patch("app.llm.reference_recovery.call_json") as mocked:
            out, report = recover_references_with_agent(doc, rules={"reference_recovery_enabled": False})
        mocked.assert_not_called()
        self.assertEqual(len(out.references), 0)
        self.assertEqual(report.get("status"), "disabled")

    def test_recovers_and_normalizes_references(self) -> None:
        doc = _doc(self.md_path, refs=[])
        payload = {
            "references": [
                {"raw": "[1] Foo et al. Test Journal (2020)"},
                "2. Bar et al. Demo Journal (2021)",
                {"text": "(2) Bar et al. Demo Journal (2021)"},
                "x",
            ]
        }
        with patch("app.llm.reference_recovery.call_json", return_value=payload) as mocked:
            out, report = recover_references_with_agent(
                doc,
                rules={
                    "reference_recovery_enabled": True,
                    "reference_recovery_max_refs": 10,
                    "reference_recovery_doc_chars_max": 8000,
                },
            )
        mocked.assert_called_once()
        self.assertEqual(report.get("status"), "recovered")
        self.assertEqual(report.get("after_refs"), 2)
        self.assertEqual(len(out.references), 2)
        self.assertEqual(out.references[0].ref_num, 1)
        self.assertEqual(out.references[1].ref_num, 2)
        self.assertTrue(out.references[0].raw.startswith("Foo et al."))
        self.assertTrue(out.references[1].raw.startswith("Bar et al."))

    def test_agent_error_uses_heuristic_fallback(self) -> None:
        doc = _doc(self.md_path, refs=[])
        with patch("app.llm.reference_recovery.call_json", side_effect=RuntimeError("boom")):
            out, report = recover_references_with_agent(doc, rules={"reference_recovery_enabled": True})
        self.assertGreater(len(out.references), 0)
        self.assertEqual(report.get("status"), "recovered_heuristic_after_agent_error")
        self.assertTrue(bool(report.get("heuristic_used")))
        self.assertIn("boom", str(report.get("error") or ""))

    def test_agent_error_without_reference_section_keeps_empty(self) -> None:
        md2 = str(Path(self.tmp.name) / "no_refs.md")
        Path(md2).write_text("# Title\n\nNo bibliography here.\n", encoding="utf-8")
        doc = _doc(md2, refs=[])
        with patch("app.llm.reference_recovery.call_json", side_effect=RuntimeError("boom")):
            out, report = recover_references_with_agent(doc, rules={"reference_recovery_enabled": True})
        self.assertEqual(len(out.references), 0)
        self.assertEqual(report.get("status"), "agent_error")

    def test_agent_error_uses_heuristic_when_references_only_in_tail(self) -> None:
        md3 = str(Path(self.tmp.name) / "long_tail_refs.md")
        filler = "A" * 6000
        Path(md3).write_text(
            f"# Title\n\n{filler}\n\n# REFERENCES\nFOO, A. Example Journal 12 (2018), 1-9.\nBAR, B. Demo Journal 21 (2019), 10-20.\n",
            encoding="utf-8",
        )
        doc = _doc(md3, refs=[])
        with patch("app.llm.reference_recovery.call_json", side_effect=RuntimeError("boom")):
            out, report = recover_references_with_agent(
                doc,
                rules={
                    "reference_recovery_enabled": True,
                    "reference_recovery_doc_chars_max": 800,
                    "reference_recovery_max_refs": 10,
                },
            )
        self.assertGreaterEqual(len(out.references), 2)
        self.assertEqual(report.get("status"), "recovered_heuristic_after_agent_error")
        self.assertTrue(bool(report.get("heuristic_used")))

    def test_agent_timeout_uses_heuristic_fallback(self) -> None:
        doc = _doc(self.md_path, refs=[])

        def _slow_call_json(*_args, **_kwargs):
            time.sleep(0.9)
            return {"references": []}

        with patch("app.llm.reference_recovery.call_json", side_effect=_slow_call_json):
            out, report = recover_references_with_agent(
                doc,
                rules={
                    "reference_recovery_enabled": True,
                    "reference_recovery_agent_timeout_sec": 0.5,
                },
            )
        self.assertGreater(len(out.references), 0)
        self.assertEqual(report.get("status"), "recovered_heuristic_after_agent_timeout")
        self.assertTrue(bool(report.get("heuristic_used")))


if __name__ == "__main__":
    unittest.main()
