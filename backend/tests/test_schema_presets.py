from __future__ import annotations

import copy
import unittest

from app.schema_presets import PRESET_IDS, apply_schema_preset, list_schema_presets
from app.schema_store import validate_schema


def _base_schema(paper_type: str = "research") -> dict:
    if paper_type == "review":
        steps = [
            {"id": "Background", "enabled": True, "order": 0},
            {"id": "Scope", "enabled": True, "order": 1},
            {"id": "Taxonomy", "enabled": True, "order": 2},
            {"id": "Comparison", "enabled": True, "order": 3},
            {"id": "Gap", "enabled": True, "order": 4},
            {"id": "Conclusion", "enabled": True, "order": 5},
        ]
    else:
        steps = [
            {"id": "Background", "enabled": True, "order": 0},
            {"id": "Problem", "enabled": True, "order": 1},
            {"id": "Method", "enabled": True, "order": 2},
            {"id": "Experiment", "enabled": True, "order": 3},
            {"id": "Result", "enabled": True, "order": 4},
            {"id": "Conclusion", "enabled": True, "order": 5},
        ]

    return {
        "paper_type": paper_type,
        "version": 1,
        "steps": steps,
        "claim_kinds": [
            {"id": "Definition", "enabled": True},
            {"id": "Method", "enabled": True},
            {"id": "Result", "enabled": True},
            {"id": "Conclusion", "enabled": True},
            {"id": "Gap", "enabled": True},
            {"id": "Critique", "enabled": True},
            {"id": "Limitation", "enabled": True},
            {"id": "FutureWork", "enabled": True},
            {"id": "Comparison", "enabled": True},
            {"id": "Assumption", "enabled": True},
            {"id": "Scope", "enabled": True},
            {"id": "Taxonomy", "enabled": True},
        ],
        "rules": {
            "claims_per_paper_min": 24,
            "claims_per_paper_max": 48,
            "machine_evidence_min": 1,
            "machine_evidence_max": 2,
            "logic_evidence_min": 1,
            "logic_evidence_max": 2,
            "citation_context_sentence_window": 1,
            "targets_per_claim_max": 3,
            "require_targets_for_kinds": ["Gap", "Critique", "Limitation", "Comparison"],
            "evidence_verification": "llm",
        },
    }


class SchemaPresetsTests(unittest.TestCase):
    def test_lists_three_builtin_presets(self) -> None:
        items = list_schema_presets()
        ids = [str(item["id"]) for item in items]
        self.assertEqual(ids, list(PRESET_IDS))

    def test_apply_preset_attaches_full_prompts_and_valid_rules(self) -> None:
        schema = _base_schema("research")
        out = apply_schema_preset(schema, preset_id="high_precision")
        prompts = dict(out.get("prompts") or {})
        self.assertEqual(
            set(prompts.keys()),
            {
                "logic_claims_system",
                "logic_claims_user_template",
                "evidence_pick_system",
                "evidence_pick_user_template",
                "phase1_logic_bind_system",
                "phase1_logic_bind_user_template",
                "phase1_chunk_claim_extract_system",
                "phase1_chunk_claim_extract_user_template",
                "phase1_grounding_judge_system",
                "phase1_grounding_judge_user_template",
                "phase2_conflict_judge_system",
                "phase2_conflict_judge_user_template",
                "citation_purpose_batch_system",
                "citation_purpose_batch_user_template",
                "reference_recovery_system",
                "reference_recovery_user_template",
            },
        )
        self.assertTrue(all(str(v).strip() for v in prompts.values()))
        validate_schema(out)

    def test_apply_preset_keeps_structure_and_changes_strategy_values(self) -> None:
        schema = _base_schema("research")
        original_steps = copy.deepcopy(schema["steps"])
        original_kinds = copy.deepcopy(schema["claim_kinds"])
        precision = apply_schema_preset(schema, preset_id="high_precision")
        recall = apply_schema_preset(schema, preset_id="high_recall")
        balanced = apply_schema_preset(schema, preset_id="balanced")

        self.assertEqual(precision["steps"], original_steps)
        self.assertEqual(precision["claim_kinds"], original_kinds)

        pmin = int((precision.get("rules") or {}).get("claims_per_paper_min", 0))
        bmin = int((balanced.get("rules") or {}).get("claims_per_paper_min", 0))
        rmin = int((recall.get("rules") or {}).get("claims_per_paper_min", 0))
        self.assertLess(pmin, bmin)
        self.assertLess(bmin, rmin)

        p_timeout = float((precision.get("rules") or {}).get("reference_recovery_agent_timeout_sec", 0.0))
        b_timeout = float((balanced.get("rules") or {}).get("reference_recovery_agent_timeout_sec", 0.0))
        r_timeout = float((recall.get("rules") or {}).get("reference_recovery_agent_timeout_sec", 0.0))
        self.assertLess(p_timeout, b_timeout)
        self.assertLess(b_timeout, r_timeout)

    def test_apply_preset_is_valid_for_review_schema(self) -> None:
        schema = _base_schema("review")
        for preset_id in PRESET_IDS:
            out = apply_schema_preset(schema, preset_id=preset_id)
            validate_schema(out)


if __name__ == "__main__":
    unittest.main()
