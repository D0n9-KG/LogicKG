from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingest.models import Chunk, DocumentIR, MdSpan, PaperDraft


class Phase1ExtractionOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="logickg-phase1-orchestrator-")
        self.artifacts_dir = Path(self._tmpdir)
        self.schema = {
            "paper_type": "research",
            "version": 1,
            "steps": [
                {"id": "Background", "enabled": True, "order": 0},
                {"id": "Method", "enabled": True, "order": 1},
            ],
            "claim_kinds": [
                {"id": "Definition", "enabled": True},
                {"id": "Comparison", "enabled": True},
            ],
            "rules": {
                "require_targets_for_kinds": ["Comparison"],
                "targets_per_claim_max": 3,
            },
        }
        self.doc = DocumentIR(
            paper=PaperDraft(
                paper_source="paperA",
                md_path="C:/tmp/paperA/source.md",
                title="Paper A",
                title_alt=None,
                authors=["Alice"],
                doi="10.1000/papera",
                year=2024,
            ),
            chunks=[
                Chunk(
                    chunk_id="c1",
                    paper_source="paperA",
                    md_path="C:/tmp/paperA/source.md",
                    span=MdSpan(start_line=10, end_line=12),
                    section="Background",
                    kind="block",
                    text="This paper defines X and compares to prior work.",
                ),
                Chunk(
                    chunk_id="c2",
                    paper_source="paperA",
                    md_path="C:/tmp/paperA/source.md",
                    span=MdSpan(start_line=20, end_line=22),
                    section="Method",
                    kind="block",
                    text="Our method uses finite elements.",
                ),
            ],
            references=[],
            citations=[],
        )
        self.cite_rec = {
            "cites_resolved": [
                {
                    "cited_paper_id": "doi:10.2000/refa",
                    "total_mentions": 3,
                    "evidence_chunk_ids": ["c1"],
                }
            ]
        }

    def tearDown(self) -> None:
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_phase1_orchestration_builds_validated_track_and_artifacts(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Background": {
                        "summary": "Background summary",
                        "confidence": 0.82,
                        "evidence_chunk_ids": ["c1"],
                        "evidence_weak": False,
                    },
                    "Method": {
                        "summary": "Method summary",
                        "confidence": 0.79,
                        "evidence_chunk_ids": ["c2"],
                        "evidence_weak": False,
                    },
                },
                "step_order": ["Background", "Method"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "This paper defines X.",
                    "confidence": 0.8,
                    "step_type": "Background",
                    "kinds": ["Definition"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                },
                {
                    "text": "Our method uses finite elements.",
                    "confidence": 0.75,
                    "step_type": "Method",
                    "kinds": ["Comparison"],
                    "origin_chunk_id": "c2",
                    "worker_id": "w2",
                },
            ]

        def fake_judge(*, claims, chunk_by_id, schema):
            by_text = {
                "this paper defines x": ("supported", 0.93, "directly stated"),
                "our method uses finite elements": ("unsupported", 0.22, "not directly entailed"),
            }
            out = []
            for c in claims:
                key = str(c["text"]).strip().lower().rstrip(".;。；")
                lbl, score, reason = by_text[key]
                out.append(
                    {
                        "canonical_claim_id": c["canonical_claim_id"],
                        "support_label": lbl,
                        "judge_score": score,
                        "reason": reason,
                    }
                )
            return out

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=self.schema,
            artifacts_dir=self.artifacts_dir,
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )

        self.assertEqual(len(out["validated_claims"]), 2)
        self.assertEqual(len(out["rejected_claims"]), 0)
        accepted = out["validated_claims"][0]
        self.assertEqual(accepted["evidence_chunk_ids"], ["c1"])
        self.assertEqual(accepted["support_label"], "supported")
        self.assertEqual(accepted["step_type"], "Background")
        self.assertAlmostEqual(float(out["quality_report"]["supported_claim_ratio"]), 1.0, places=2)
        self.assertTrue(bool(out["quality_report"]["gate_passed"]))

        expected_files = [
            "logic_steps.json",
            "claim_candidates.json",
            "claims_merged.json",
            "grounding_judgment.json",
            "completeness_judgment.json",
            "quality_report.json",
        ]
        for name in expected_files:
            p = self.artifacts_dir / name
            self.assertTrue(p.exists(), f"{name} missing")
            _ = json.loads(p.read_text(encoding="utf-8"))

    def test_allow_weak_controls_gate_behavior(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Background": {
                        "summary": "Background summary",
                        "confidence": 0.82,
                        "evidence_chunk_ids": ["c1"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Background"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "This is weakly supported.",
                    "confidence": 0.66,
                    "step_type": "Background",
                    "kinds": ["Definition"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                }
            ]

        def fake_judge(*, claims, chunk_by_id, schema):
            return [
                {
                    "canonical_claim_id": claims[0]["canonical_claim_id"],
                    "support_label": "weak",
                    "judge_score": 0.51,
                    "reason": "partial support",
                }
            ]

        out_disallow = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=self.schema,
            artifacts_dir=self.artifacts_dir / "disallow",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )
        self.assertEqual(len(out_disallow["validated_claims"]), 1)
        self.assertEqual(len(out_disallow["rejected_claims"]), 0)

        out_allow = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=self.schema,
            artifacts_dir=self.artifacts_dir / "allow",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=True,
        )
        self.assertEqual(len(out_allow["validated_claims"]), 1)
        self.assertEqual(out_allow["validated_claims"][0]["support_label"], "supported")

    def test_targets_are_mapped_from_citation_evidence_chunks(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Method": {
                        "summary": "Method summary",
                        "confidence": 0.79,
                        "evidence_chunk_ids": ["c1"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Method"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "Method outperforms baseline.",
                    "confidence": 0.77,
                    "step_type": "Method",
                    "kinds": ["Comparison"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                }
            ]

        def fake_judge(*, claims, chunk_by_id, schema):
            return [
                {
                    "canonical_claim_id": claims[0]["canonical_claim_id"],
                    "support_label": "supported",
                    "judge_score": 0.91,
                    "reason": "explicitly stated",
                }
            ]

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=self.schema,
            artifacts_dir=self.artifacts_dir / "targets",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )
        self.assertEqual(len(out["validated_claims"]), 1)
        self.assertEqual(out["validated_claims"][0]["targets_paper_ids"], ["doi:10.2000/refa"])

    def test_quality_report_includes_completeness_and_missing_slots(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        schema = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.0,
                "phase2_gate_critical_slot_coverage_min": 0.9,
                "phase2_gate_conflict_rate_max": 1.0,
                "phase2_critical_steps": ["Background"],
                "phase2_critical_kinds": ["Definition", "Comparison"],
            },
        }

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Background": {
                        "summary": "Background summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c1"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Background"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "This paper defines X.",
                    "confidence": 0.8,
                    "step_type": "Background",
                    "kinds": ["Definition"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                }
            ]

        def fake_judge(*, claims, chunk_by_id, schema):
            return [
                {
                    "canonical_claim_id": claims[0]["canonical_claim_id"],
                    "support_label": "supported",
                    "judge_score": 0.9,
                    "reason": "explicit support",
                }
            ]

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema,
            artifacts_dir=self.artifacts_dir / "phase2_completeness",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )

        report = out["quality_report"]
        self.assertIn("critical_slot_coverage", report)
        self.assertIn("missing_critical_slots", report)
        self.assertAlmostEqual(float(report["critical_slot_coverage"]), 0.5, places=3)
        self.assertIn("Background|Comparison", report["missing_critical_slots"])
        self.assertFalse(bool(report["gate_passed"]))
        self.assertIn("critical_slot_coverage", report.get("gate_fail_reasons") or [])

    def test_quality_report_supports_step_kind_map_slots(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        schema = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.0,
                "phase2_gate_critical_slot_coverage_min": 1.0,
                "phase2_gate_conflict_rate_max": 1.0,
                "phase2_critical_step_kind_map": {"Background": ["Definition"]},
            },
        }

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Background": {
                        "summary": "Background summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c1"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Background"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "This paper defines X.",
                    "confidence": 0.8,
                    "step_type": "Background",
                    "kinds": ["Definition"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                }
            ]

        def fake_judge(*, claims, chunk_by_id, schema):
            return [
                {
                    "canonical_claim_id": claims[0]["canonical_claim_id"],
                    "support_label": "supported",
                    "judge_score": 0.9,
                    "reason": "explicit support",
                }
            ]

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema,
            artifacts_dir=self.artifacts_dir / "phase2_step_kind_map",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )

        report = out["quality_report"]
        self.assertAlmostEqual(float(report["critical_slot_coverage"]), 1.0, places=3)
        self.assertEqual(report.get("missing_critical_slots"), [])
        self.assertEqual(str(report.get("critical_slot_mode") or ""), "step_kind_map")
        self.assertEqual(int(report.get("critical_slots_total") or 0), 1)
        self.assertEqual(dict(report.get("critical_step_kind_map") or {}), {"Background": ["Definition"]})
        self.assertTrue(bool(report["gate_passed"]))

    def test_step_kind_map_overrides_cartesian_step_kind_slots(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        schema = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.0,
                "phase2_gate_critical_slot_coverage_min": 1.0,
                "phase2_gate_conflict_rate_max": 1.0,
                "phase2_critical_steps": ["Background"],
                "phase2_critical_kinds": ["Definition", "Comparison"],
                "phase2_critical_step_kind_map": {"Background": ["Definition"]},
            },
        }

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Background": {
                        "summary": "Background summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c1"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Background"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "This paper defines X.",
                    "confidence": 0.8,
                    "step_type": "Background",
                    "kinds": ["Definition"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                }
            ]

        def fake_judge(*, claims, chunk_by_id, schema):
            return [
                {
                    "canonical_claim_id": claims[0]["canonical_claim_id"],
                    "support_label": "supported",
                    "judge_score": 0.9,
                    "reason": "explicit support",
                }
            ]

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema,
            artifacts_dir=self.artifacts_dir / "phase2_step_kind_map_override",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )

        report = out["quality_report"]
        self.assertEqual(str(report.get("critical_slot_mode") or ""), "step_kind_map")
        self.assertEqual(int(report.get("critical_slots_total") or 0), 1)
        self.assertAlmostEqual(float(report.get("critical_slot_coverage") or 0.0), 1.0, places=3)
        self.assertTrue(bool(report.get("gate_passed")))

    def test_auto_step_kind_map_reduces_wide_cartesian_slots(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        schema = {
            **self.schema,
            "steps": [
                {"id": "Background", "enabled": True, "order": 0},
                {"id": "Method", "enabled": True, "order": 1},
                {"id": "Experiment", "enabled": True, "order": 2},
                {"id": "Result", "enabled": True, "order": 3},
            ],
            "claim_kinds": [
                {"id": "Definition", "enabled": True},
                {"id": "Method", "enabled": True},
                {"id": "Result", "enabled": True},
                {"id": "Comparison", "enabled": True},
                {"id": "Gap", "enabled": True},
            ],
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.0,
                "phase2_gate_critical_slot_coverage_min": 0.2,
                "phase2_gate_conflict_rate_max": 1.0,
                "phase2_critical_steps": ["Background", "Method", "Experiment", "Result"],
                "phase2_critical_kinds": ["Definition", "Method", "Result", "Comparison"],
                "phase2_auto_step_kind_map_enabled": True,
                "phase2_auto_step_kind_map_trigger_slots": 12,
                "phase2_auto_step_kind_map_max_kinds_per_step": 1,
            },
        }

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Method": {
                        "summary": "Method summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c2"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Background", "Method", "Experiment", "Result"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "Our method uses finite elements.",
                    "confidence": 0.8,
                    "step_type": "Method",
                    "kinds": ["Method"],
                    "origin_chunk_id": "c2",
                    "worker_id": "w1",
                }
            ]

        def fake_judge(*, claims, chunk_by_id, schema):
            return [
                {
                    "canonical_claim_id": claims[0]["canonical_claim_id"],
                    "support_label": "supported",
                    "judge_score": 0.9,
                    "reason": "explicit support",
                }
            ]

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema,
            artifacts_dir=self.artifacts_dir / "phase2_auto_step_kind_map",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )

        report = out["quality_report"]
        self.assertEqual(str(report.get("critical_slot_mode") or ""), "step_kind_map_auto")
        self.assertEqual(int(report.get("critical_slots_total") or 0), 4)
        self.assertAlmostEqual(float(report.get("critical_slot_coverage") or 0.0), 0.25, places=3)
        self.assertTrue(bool(report.get("gate_passed")))

    def test_quality_report_conflict_rate_blocks_gate(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        schema = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.0,
                "phase2_gate_critical_slot_coverage_min": 0.0,
                "phase2_gate_conflict_rate_max": 0.0,
                "phase2_conflict_gate_min_comparable_pairs": 1,
                "phase2_conflict_gate_min_conflict_pairs": 1,
                "phase2_critical_steps": ["Method"],
                "phase2_critical_kinds": ["Comparison"],
            },
        }

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Method": {
                        "summary": "Method summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c2"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Method"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "Method improves accuracy over baseline.",
                    "confidence": 0.84,
                    "step_type": "Method",
                    "kinds": ["Comparison"],
                    "origin_chunk_id": "c2",
                    "worker_id": "w1",
                },
                {
                    "text": "Method reduces accuracy over baseline.",
                    "confidence": 0.82,
                    "step_type": "Method",
                    "kinds": ["Comparison"],
                    "origin_chunk_id": "c2",
                    "worker_id": "w2",
                },
            ]

        def fake_judge(*, claims, chunk_by_id, schema):
            out = []
            for c in claims:
                out.append(
                    {
                        "canonical_claim_id": c["canonical_claim_id"],
                        "support_label": "supported",
                        "judge_score": 0.9,
                        "reason": "explicit support",
                    }
                )
            return out

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema,
            artifacts_dir=self.artifacts_dir / "phase2_conflict",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )

        report = out["quality_report"]
        self.assertIn("conflict_rate", report)
        self.assertGreater(float(report["conflict_rate"]), 0.0)
        self.assertIn("conflict_pairs", report)
        self.assertFalse(bool(report["gate_passed"]))
        self.assertIn("conflict_rate", report.get("gate_fail_reasons") or [])

    def test_conflict_gate_ignores_small_sample_pairs(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        schema = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.0,
                "phase2_gate_critical_slot_coverage_min": 0.0,
                "phase2_gate_conflict_rate_max": 0.0,
                "phase2_conflict_gate_min_comparable_pairs": 5,
                "phase2_conflict_gate_min_conflict_pairs": 2,
                "phase2_critical_steps": ["Method"],
                "phase2_critical_kinds": ["Comparison"],
            },
        }

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Method": {
                        "summary": "Method summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c2"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Method"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "Method improves accuracy over baseline.",
                    "confidence": 0.84,
                    "step_type": "Method",
                    "kinds": ["Comparison"],
                    "origin_chunk_id": "c2",
                    "worker_id": "w1",
                },
                {
                    "text": "Method reduces accuracy over baseline.",
                    "confidence": 0.82,
                    "step_type": "Method",
                    "kinds": ["Comparison"],
                    "origin_chunk_id": "c2",
                    "worker_id": "w2",
                },
            ]

        def fake_judge(*, claims, chunk_by_id, schema):
            out = []
            for c in claims:
                out.append(
                    {
                        "canonical_claim_id": c["canonical_claim_id"],
                        "support_label": "supported",
                        "judge_score": 0.9,
                        "reason": "explicit support",
                    }
                )
            return out

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema,
            artifacts_dir=self.artifacts_dir / "phase2_conflict_small_sample",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )

        report = out["quality_report"]
        self.assertGreater(float(report["conflict_rate"]), 0.0)
        self.assertTrue(bool(report.get("conflict_gate_skipped")))
        self.assertIn("low_comparable_pairs", list(report.get("conflict_gate_skip_reasons") or []))
        self.assertTrue(bool(report["gate_passed"]))

    def test_conflict_rate_supports_custom_polarity_vocab(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        schema = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.0,
                "phase2_gate_critical_slot_coverage_min": 0.0,
                "phase2_gate_conflict_rate_max": 0.0,
                "phase2_conflict_gate_min_comparable_pairs": 1,
                "phase2_conflict_gate_min_conflict_pairs": 1,
                "phase2_critical_steps": ["Method"],
                "phase2_critical_kinds": ["Comparison"],
                "phase2_conflict_positive_terms_en": ["elevates"],
                "phase2_conflict_negative_terms_en": ["suppresses"],
            },
        }

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Method": {
                        "summary": "Method summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c2"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Method"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "Method elevates stiffness over baseline.",
                    "confidence": 0.84,
                    "step_type": "Method",
                    "kinds": ["Comparison"],
                    "origin_chunk_id": "c2",
                    "worker_id": "w1",
                },
                {
                    "text": "Method suppresses stiffness over baseline.",
                    "confidence": 0.82,
                    "step_type": "Method",
                    "kinds": ["Comparison"],
                    "origin_chunk_id": "c2",
                    "worker_id": "w2",
                },
            ]

        def fake_judge(*, claims, chunk_by_id, schema):
            out = []
            for c in claims:
                out.append(
                    {
                        "canonical_claim_id": c["canonical_claim_id"],
                        "support_label": "supported",
                        "judge_score": 0.9,
                        "reason": "explicit support",
                    }
                )
            return out

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema,
            artifacts_dir=self.artifacts_dir / "phase2_conflict_vocab",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )

        report = out["quality_report"]
        self.assertGreater(float(report["conflict_rate"]), 0.0)
        self.assertFalse(bool(report["gate_passed"]))

    def test_quality_tier_routing_uses_fail_count_strategy(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Background": {
                        "summary": "Background summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c1"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Background", "Method"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "This paper defines X.",
                    "confidence": 0.82,
                    "step_type": "Background",
                    "kinds": ["Definition"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                }
            ]

        schema_green = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.4,
                "phase2_gate_critical_slot_coverage_min": 0.0,
                "phase2_gate_conflict_rate_max": 1.0,
                "phase2_quality_tier_strategy": "a1_fail_count",
                "phase2_quality_tier_yellow_max_failures": 1,
                "phase2_quality_tier_red_min_failures": 2,
            },
        }
        out_green = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema_green,
            artifacts_dir=self.artifacts_dir / "phase2_tier_green",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )
        report_green = out_green["quality_report"]
        self.assertEqual(str(report_green.get("quality_tier") or ""), "green")
        self.assertTrue(bool(report_green.get("gate_passed")))

        schema_yellow = {
            **self.schema,
            "rules": {
                **schema_green["rules"],
                "phase1_gate_step_coverage_min": 0.8,
            },
        }
        out_yellow = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema_yellow,
            artifacts_dir=self.artifacts_dir / "phase2_tier_yellow",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )
        report_yellow = out_yellow["quality_report"]
        self.assertEqual(str(report_yellow.get("quality_tier") or ""), "yellow")
        self.assertFalse(bool(report_yellow.get("gate_passed")))
        self.assertEqual(int(report_yellow.get("quality_tier_fail_count") or 0), 1)

        schema_red = {
            **self.schema,
            "rules": {
                **schema_yellow["rules"],
                "phase2_gate_critical_slot_coverage_min": 1.0,
                "phase2_critical_steps": ["Background", "Method"],
                "phase2_critical_kinds": [],
            },
        }
        out_red = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema_red,
            artifacts_dir=self.artifacts_dir / "phase2_tier_red",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )
        report_red = out_red["quality_report"]
        self.assertEqual(str(report_red.get("quality_tier") or ""), "red")
        self.assertEqual(int(report_red.get("quality_tier_fail_count") or 0), 2)
        self.assertFalse(bool(report_red.get("gate_passed")))

    def test_quality_tier_thresholds_are_configurable(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        schema = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.8,
                "phase2_gate_critical_slot_coverage_min": 1.0,
                "phase2_gate_conflict_rate_max": 1.0,
                "phase2_critical_steps": ["Background", "Method"],
                "phase2_quality_tier_strategy": "a1_fail_count",
                "phase2_quality_tier_yellow_max_failures": 2,
                "phase2_quality_tier_red_min_failures": 3,
            },
        }

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Background": {
                        "summary": "Background summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c1"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Background", "Method"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "This paper defines X.",
                    "confidence": 0.82,
                    "step_type": "Background",
                    "kinds": ["Definition"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                }
            ]

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema,
            artifacts_dir=self.artifacts_dir / "phase2_tier_custom_thresholds",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )
        report = out["quality_report"]
        self.assertEqual(int(report.get("quality_tier_fail_count") or 0), 2)
        self.assertEqual(str(report.get("quality_tier") or ""), "yellow")

    def test_priority_chunks_excludes_reference_sections(self) -> None:
        from app.extraction.orchestrator import _priority_chunks

        doc = DocumentIR(
            paper=self.doc.paper,
            chunks=[
                self.doc.chunks[0],
                self.doc.chunks[1],
                Chunk(
                    chunk_id="c3",
                    paper_source="paperA",
                    md_path="C:/tmp/paperA/source.md",
                    span=MdSpan(start_line=100, end_line=101),
                    section="References",
                    kind="block",
                    text="A long reference list item.",
                ),
            ],
            references=[],
            citations=[],
        )
        picked = _priority_chunks(doc, logic={}, max_chunks=10)
        picked_ids = {str(x.get("chunk_id") or "") for x in picked}
        self.assertIn("c1", picked_ids)
        self.assertIn("c2", picked_ids)
        self.assertNotIn("c3", picked_ids)

    def test_priority_chunks_can_disable_reference_section_filter(self) -> None:
        from app.extraction.orchestrator import _priority_chunks

        doc = DocumentIR(
            paper=self.doc.paper,
            chunks=[
                Chunk(
                    chunk_id="c3",
                    paper_source="paperA",
                    md_path="C:/tmp/paperA/source.md",
                    span=MdSpan(start_line=100, end_line=101),
                    section="References",
                    kind="block",
                    text="A long reference list item.",
                ),
            ],
            references=[],
            citations=[],
        )
        picked = _priority_chunks(doc, logic={}, max_chunks=10, rules={"phase1_filter_reference_sections": False})
        self.assertEqual([str(x.get("chunk_id") or "") for x in picked], ["c3"])

    def test_grounding_overlap_thresholds_are_configurable(self) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        schema = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.0,
                "phase2_gate_critical_slot_coverage_min": 0.0,
                "phase2_gate_conflict_rate_max": 1.0,
                "phase1_grounding_supported_overlap_min": 0.9,
                "phase1_grounding_weak_overlap_min": 0.6,
            },
        }

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Background": {
                        "summary": "Background summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c1"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Background"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "This paper defines X tensor",
                    "confidence": 0.8,
                    "step_type": "Background",
                    "kinds": ["Definition"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                }
            ]

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema,
            artifacts_dir=self.artifacts_dir / "phase2_grounding_thresholds",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )

        # With grounding skipped, all claims are validated regardless of overlap thresholds
        self.assertEqual(len(out["validated_claims"]), 1)
        self.assertEqual(len(out["rejected_claims"]), 0)
        self.assertEqual(out["validated_claims"][0]["support_label"], "supported")

    @patch("app.llm.grounding_judge_v2.judge_claim_support_batch")
    def test_grounding_mode_hybrid_uses_llm_for_uncertain_claims(self, mock_judge_batch) -> None:
        """With grounding skipped, hybrid mode is no longer used. All claims are supported."""
        from app.extraction.orchestrator import run_phase1_extraction

        schema = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.0,
                "phase2_gate_critical_slot_coverage_min": 0.0,
                "phase2_gate_conflict_rate_max": 1.0,
            },
        }

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Background": {
                        "summary": "Background summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c1"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Background"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "Prior studies establish the definition of X.",
                    "confidence": 0.81,
                    "step_type": "Background",
                    "kinds": ["Definition"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                }
            ]

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema,
            artifacts_dir=self.artifacts_dir / "phase1_grounding_hybrid",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,
            allow_weak=False,
        )

        report = out["quality_report"]
        self.assertEqual(len(out["validated_claims"]), 1)
        self.assertEqual(out["validated_claims"][0]["support_label"], "supported")
        self.assertEqual(str(report.get("grounding_mode_used") or ""), "skip")
        self.assertEqual(int(report.get("grounding_semantic_judged") or 0), 0)
        mock_judge_batch.assert_not_called()

    @patch("app.llm.conflict_judge.judge_conflict_pairs_batch")
    def test_conflict_mode_llm_uses_semantic_judge(self, mock_conflict_batch) -> None:
        from app.extraction.orchestrator import run_phase1_extraction

        schema = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.0,
                "phase2_gate_critical_slot_coverage_min": 0.0,
                "phase2_gate_conflict_rate_max": 0.0,
                "phase2_conflict_gate_min_comparable_pairs": 1,
                "phase2_conflict_gate_min_conflict_pairs": 1,
                "phase2_conflict_mode": "llm",
                "phase2_conflict_semantic_threshold": 0.7,
                "phase2_conflict_candidate_max_pairs": 50,
                "phase2_critical_steps": ["Method"],
                "phase2_critical_kinds": ["Comparison"],
            },
        }

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Method": {
                        "summary": "Method summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c2"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Method"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "Method improves accuracy over baseline.",
                    "confidence": 0.84,
                    "step_type": "Method",
                    "kinds": ["Comparison"],
                    "origin_chunk_id": "c2",
                    "worker_id": "w1",
                },
                {
                    "text": "Method reduces accuracy over baseline.",
                    "confidence": 0.82,
                    "step_type": "Method",
                    "kinds": ["Comparison"],
                    "origin_chunk_id": "c2",
                    "worker_id": "w2",
                },
            ]

        def _mock_conflict(*, pairs, schema):
            return [
                {
                    "pair_id": str(pairs[0].get("pair_id") or ""),
                    "label": "contradict",
                    "score": 0.91,
                    "reason": "same metric opposite direction",
                }
            ]

        mock_conflict_batch.side_effect = _mock_conflict

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema,
            artifacts_dir=self.artifacts_dir / "phase2_conflict_llm",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,

            allow_weak=False,
        )

        report = out["quality_report"]
        self.assertEqual(str(report.get("conflict_mode_used") or ""), "llm")
        self.assertGreater(int(report.get("conflict_semantic_judged") or 0), 0)
        self.assertGreater(float(report.get("conflict_rate") or 0.0), 0.0)
        self.assertFalse(bool(report.get("gate_passed")))
        self.assertIn("conflict_rate", list(report.get("gate_fail_reasons") or []))
        mock_conflict_batch.assert_called_once()

    def test_default_logic_extractor_uses_quote_matching(self) -> None:
        """Test that _default_logic_extractor uses extract_logic_and_claims_v2 and filters empty steps."""
        from app.extraction.orchestrator import _default_logic_extractor

        extracted_logic = {
            "logic": {
                "Background": {"summary": "Background summary.", "confidence": 0.81, "evidence_chunk_ids": ["c1"]},
                "Method": {"summary": "Method summary.", "confidence": 0.79, "evidence_chunk_ids": ["c2"]},
            }
        }

        with patch("app.llm.logic_claims_v2.extract_logic_and_claims_v2", return_value=extracted_logic):
            out = _default_logic_extractor(doc=self.doc, paper_id="doi:10.1000/papera", schema=self.schema)

        self.assertEqual(out["logic"]["Background"]["evidence_chunk_ids"], ["c1"])
        self.assertEqual(out["logic"]["Method"]["evidence_chunk_ids"], ["c2"])

    def test_default_logic_extractor_filters_empty_steps(self) -> None:
        """Test that _default_logic_extractor filters out steps with no summary and no evidence."""
        from app.extraction.orchestrator import _default_logic_extractor

        extracted_logic = {
            "logic": {
                "Background": {"summary": "Background summary.", "confidence": 0.81, "evidence_chunk_ids": ["c1"]},
                "Method": {"summary": "", "confidence": 0.0},
            }
        }

        with patch("app.llm.logic_claims_v2.extract_logic_and_claims_v2", return_value=extracted_logic):
            out = _default_logic_extractor(doc=self.doc, paper_id="doi:10.1000/papera", schema=self.schema)

        self.assertIn("Background", out["logic"])
        self.assertNotIn("Method", out["logic"])

    def test_chunk_claim_extractor_honors_schema_prompt_overrides(self) -> None:
        from app.extraction.orchestrator import _extract_claims_from_chunk_llm

        schema = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_chunk_chars_max": 32,
            },
            "prompts": {
                "phase1_chunk_claim_extract_system": "SYS-OVERRIDE",
                "phase1_chunk_claim_extract_user_template": "TEXT={{chunk_text}};STEPS={{step_ids}};KINDS={{kind_ids}};MAX={{max_claims}}",
            },
        }

        with patch("app.llm.client.call_json", return_value={"claims": [{"text": "A defined claim.", "evidence_quote": "ABCDEFGHIJKLMNOPQRST", "step_type": "Background", "claim_kinds": ["Definition"], "confidence": 0.8}]}) as call_json:
            out = _extract_claims_from_chunk_llm(
                chunk_text="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
                step_ids=["Background"],
                kind_ids=["Definition"],
                max_claims=2,
                schema=schema,
            )

        self.assertEqual(len(out), 1)
        args = call_json.call_args[0]
        self.assertEqual(args[0], "SYS-OVERRIDE")
        self.assertIn("TEXT=ABCDEFGHIJKLMNOPQRSTUVWXYZ012345", args[1])
        self.assertIn("MAX=2", args[1])

    def test_logic_extraction_uses_evidence_quotes(self) -> None:
        """Test that logic extraction now uses evidence_quotes instead of chunk catalog."""
        from app.extraction.orchestrator import _default_logic_extractor

        extracted_logic = {
            "logic": {
                "Background": {
                    "summary": "Background summary.",
                    "confidence": 0.81,
                    "evidence_quotes": ["some verbatim quote"],
                    "evidence_chunk_ids": ["c1"],
                },
                "Method": {
                    "summary": "Method summary.",
                    "confidence": 0.7,
                    "evidence_quotes": ["another quote"],
                    "evidence_chunk_ids": ["c2"],
                },
            }
        }

        with patch("app.llm.logic_claims_v2.extract_logic_and_claims_v2", return_value=extracted_logic):
            out = _default_logic_extractor(doc=self.doc, paper_id="doi:10.1000/papera", schema=self.schema)

        self.assertIn("Background", out["logic"])
        self.assertIn("Method", out["logic"])
        self.assertEqual(out["logic"]["Background"]["evidence_chunk_ids"], ["c1"])

    def test_noise_filter_integration_filters_captions_and_definitions(self) -> None:
        """Test that noise filters are applied during extraction when enabled."""
        from app.extraction.orchestrator import run_phase1_extraction

        schema = {
            **self.schema,
            "rules": {
                **self.schema.get("rules", {}),
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.0,
                "phase2_gate_critical_slot_coverage_min": 0.0,
                "phase2_gate_conflict_rate_max": 1.0,
                "phase1_noise_filter_enabled": True,
                "phase1_noise_filter_figure_caption_enabled": True,
                "phase1_noise_filter_pure_definition_enabled": True,
                "phase1_noise_filter_context_aware": False,
            },
        }

        def fake_logic_extractor(*, doc, paper_id, schema):
            return {
                "logic": {
                    "Background": {
                        "summary": "Background summary",
                        "confidence": 0.8,
                        "evidence_chunk_ids": ["c1"],
                        "evidence_weak": False,
                    }
                },
                "step_order": ["Background"],
            }

        def fake_claim_extractor(*, doc, paper_id, schema, step_order):
            return [
                {
                    "text": "Figure 1: Experimental setup shows the process.",
                    "confidence": 0.8,
                    "step_type": "Background",
                    "kinds": ["Definition"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                },
                {
                    "text": "Machine learning is a method of data analysis.",
                    "confidence": 0.75,
                    "step_type": "Background",
                    "kinds": ["Definition"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                },
                {
                    "text": "This approach outperforms prior methods significantly.",
                    "confidence": 0.82,
                    "step_type": "Background",
                    "kinds": ["Comparison"],
                    "origin_chunk_id": "c1",
                    "worker_id": "w1",
                },
            ]

        out = run_phase1_extraction(
            doc=self.doc,
            paper_id="doi:10.1000/papera",
            cite_rec=self.cite_rec,
            schema=schema,
            artifacts_dir=self.artifacts_dir / "noise_filter_test",
            logic_extractor=fake_logic_extractor,
            claim_extractor=fake_claim_extractor,
            allow_weak=False,
        )

        # Verify filter statistics in quality report
        report = out["quality_report"]
        self.assertIn("noise_filter", report)
        filter_stats = report["noise_filter"]
        self.assertEqual(filter_stats["raw_count"], 3)
        self.assertEqual(filter_stats["filtered_count"], 1)
        self.assertEqual(filter_stats["caption_filtered"], 1)
        self.assertEqual(filter_stats["definition_filtered"], 1)
        self.assertGreater(filter_stats["filter_rate"], 0.0)

        # Verify only the comparison claim was validated (not filtered)
        self.assertEqual(len(out["validated_claims"]), 1)
        self.assertIn("outperforms", out["validated_claims"][0]["text"])


if __name__ == "__main__":
    unittest.main()
