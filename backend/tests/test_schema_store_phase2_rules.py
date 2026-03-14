from __future__ import annotations

import unittest

from app.schema_store import validate_schema


def _base_schema() -> dict:
    return {
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
            "claims_per_paper_min": 1,
            "claims_per_paper_max": 5,
            "machine_evidence_min": 1,
            "machine_evidence_max": 2,
            "logic_evidence_min": 1,
            "logic_evidence_max": 2,
            "citation_context_sentence_window": 1,
            "targets_per_claim_max": 2,
            "require_targets_for_kinds": ["Comparison"],
            "evidence_verification": "llm",
        },
    }


class SchemaStorePhase2RulesTests(unittest.TestCase):
    def test_phase2_rules_allow_zero_thresholds(self) -> None:
        schema = _base_schema()
        schema["rules"].update(
            {
                "phase1_gate_supported_ratio_min": 0.0,
                "phase1_gate_step_coverage_min": 0.0,
                "phase2_gate_critical_slot_coverage_min": 0.0,
                "phase2_gate_conflict_rate_max": 0.0,
                "phase2_critical_steps": ["Background"],
                "phase2_critical_kinds": ["Definition"],
            }
        )
        validate_schema(schema)

    def test_phase2_rejects_unknown_critical_step(self) -> None:
        schema = _base_schema()
        schema["rules"]["phase2_critical_steps"] = ["UnknownStep"]
        with self.assertRaisesRegex(ValueError, "Unknown phase2 critical step"):
            validate_schema(schema)

    def test_phase2_rejects_unknown_critical_kind(self) -> None:
        schema = _base_schema()
        schema["rules"]["phase2_critical_kinds"] = ["UnknownKind"]
        with self.assertRaisesRegex(ValueError, "Unknown phase2 critical kind"):
            validate_schema(schema)

    def test_phase2_accepts_extended_rule_knobs(self) -> None:
        schema = _base_schema()
        schema["rules"].update(
            {
                "phase1_chunk_chars_max": 2048,
                "phase1_claim_batch_size": 6,
                "phase1_claim_batch_chars_max": 9600,
                "phase1_logic_chunk_chars_max": 600,
                "phase1_logic_lexical_topk_min": 8,
                "phase1_logic_lexical_topk_multiplier": 4,
                "phase1_logic_evidence_weak_score_threshold": 1.5,
                "phase1_doc_chars_max": 32000,
                "phase1_evidence_verify_batch_size": 12,
                "phase1_evidence_lexical_topk": 12,
                "phase1_evidence_verify_candidates_max": 8,
                "phase2_conflict_shared_tokens_min": 2,
                "phase2_conflict_samples_max": 12,
                "phase2_conflict_gate_min_comparable_pairs": 4,
                "phase2_conflict_gate_min_conflict_pairs": 1,
                "phase2_conflict_mode": "hybrid",
                "phase2_conflict_semantic_threshold": 0.75,
                "phase2_conflict_candidate_max_pairs": 160,
                "phase2_quality_tier_strategy": "a1_fail_count",
                "phase2_quality_tier_yellow_max_failures": 1,
                "phase2_quality_tier_red_min_failures": 2,
                "phase2_critical_step_kind_map": {"Background": ["Definition"]},
                "phase2_auto_step_kind_map_enabled": True,
                "phase2_auto_step_kind_map_trigger_slots": 12,
                "phase2_auto_step_kind_map_max_kinds_per_step": 1,
                "phase1_grounding_mode": "hybrid",
                "phase1_grounding_semantic_supported_min": 0.75,
                "phase1_grounding_semantic_weak_min": 0.55,
                "citation_purpose_max_contexts_per_cite": 4,
                "citation_purpose_max_context_chars": 1200,
                "citation_purpose_max_cites_per_batch": 80,
                "citation_purpose_max_labels_per_cite": 4,
                "citation_purpose_fallback_score": 0.35,
                "reference_recovery_trigger_max_existing_refs": 2,
                "reference_recovery_agent_timeout_sec": 30.0,
                "citation_event_recovery_enabled": True,
                "citation_event_recovery_trigger_max_existing_events": 2,
                "citation_event_recovery_numeric_bracket_enabled": True,
                "citation_event_recovery_paren_numeric_enabled": False,
                "citation_event_recovery_author_year_enabled": True,
                "citation_event_recovery_max_events_per_chunk": 8,
                "citation_event_recovery_context_chars": 900,
            }
        )
        validate_schema(schema)

    def test_phase2_rejects_invalid_extended_rule_knobs(self) -> None:
        schema = _base_schema()
        schema["rules"]["phase1_chunk_chars_max"] = 50
        with self.assertRaisesRegex(ValueError, "phase1_chunk_chars_max"):
            validate_schema(schema)

        schema2 = _base_schema()
        schema2["rules"]["phase1_logic_chunk_chars_max"] = 50
        with self.assertRaisesRegex(ValueError, "phase1_logic_chunk_chars_max"):
            validate_schema(schema2)

        schema2b = _base_schema()
        schema2b["rules"]["phase1_claim_batch_size"] = 0
        with self.assertRaisesRegex(ValueError, "phase1_claim_batch_size"):
            validate_schema(schema2b)

        schema2c = _base_schema()
        schema2c["rules"]["phase1_claim_batch_chars_max"] = 999999
        with self.assertRaisesRegex(ValueError, "phase1_claim_batch_chars_max"):
            validate_schema(schema2c)

        schema3 = _base_schema()
        schema3["rules"]["citation_purpose_fallback_score"] = 1.5
        with self.assertRaisesRegex(ValueError, "citation_purpose_fallback_score"):
            validate_schema(schema3)

        schema4 = _base_schema()
        schema4["rules"]["phase1_evidence_verify_candidates_max"] = 0
        with self.assertRaisesRegex(ValueError, "phase1_evidence_verify_candidates_max"):
            validate_schema(schema4)

        schema5 = _base_schema()
        schema5["rules"]["reference_recovery_agent_timeout_sec"] = 0.1
        with self.assertRaisesRegex(ValueError, "reference_recovery_agent_timeout_sec"):
            validate_schema(schema5)

        schema6 = _base_schema()
        schema6["rules"]["phase2_conflict_gate_min_comparable_pairs"] = -1
        with self.assertRaisesRegex(ValueError, "phase2_conflict_gate_min_comparable_pairs"):
            validate_schema(schema6)

        schema7 = _base_schema()
        schema7["rules"]["phase2_conflict_gate_min_conflict_pairs"] = 201
        with self.assertRaisesRegex(ValueError, "phase2_conflict_gate_min_conflict_pairs"):
            validate_schema(schema7)

        schema8 = _base_schema()
        schema8["rules"]["phase2_auto_step_kind_map_trigger_slots"] = 0
        with self.assertRaisesRegex(ValueError, "phase2_auto_step_kind_map_trigger_slots"):
            validate_schema(schema8)

        schema9 = _base_schema()
        schema9["rules"]["phase2_auto_step_kind_map_max_kinds_per_step"] = 7
        with self.assertRaisesRegex(ValueError, "phase2_auto_step_kind_map_max_kinds_per_step"):
            validate_schema(schema9)

        schema10 = _base_schema()
        schema10["rules"]["phase2_conflict_mode"] = "semantic_only"
        with self.assertRaisesRegex(ValueError, "phase2_conflict_mode"):
            validate_schema(schema10)

        schema11 = _base_schema()
        schema11["rules"]["phase2_conflict_semantic_threshold"] = 1.2
        with self.assertRaisesRegex(ValueError, "phase2_conflict_semantic_threshold"):
            validate_schema(schema11)

        schema12 = _base_schema()
        schema12["rules"]["phase2_conflict_candidate_max_pairs"] = 0
        with self.assertRaisesRegex(ValueError, "phase2_conflict_candidate_max_pairs"):
            validate_schema(schema12)

        schema13 = _base_schema()
        schema13["rules"]["phase1_grounding_mode"] = "semantic_only"
        with self.assertRaisesRegex(ValueError, "phase1_grounding_mode"):
            validate_schema(schema13)

        schema14 = _base_schema()
        schema14["rules"]["phase1_grounding_semantic_supported_min"] = 0.4
        schema14["rules"]["phase1_grounding_semantic_weak_min"] = 0.6
        with self.assertRaisesRegex(ValueError, "phase1_grounding_semantic_weak_min"):
            validate_schema(schema14)

        schema15 = _base_schema()
        schema15["rules"]["phase2_quality_tier_strategy"] = "weighted"
        with self.assertRaisesRegex(ValueError, "phase2_quality_tier_strategy"):
            validate_schema(schema15)

        schema16 = _base_schema()
        schema16["rules"]["phase2_quality_tier_yellow_max_failures"] = -1
        with self.assertRaisesRegex(ValueError, "phase2_quality_tier_yellow_max_failures"):
            validate_schema(schema16)

        schema17 = _base_schema()
        schema17["rules"]["phase2_quality_tier_red_min_failures"] = 0
        with self.assertRaisesRegex(ValueError, "phase2_quality_tier_red_min_failures"):
            validate_schema(schema17)

        schema18 = _base_schema()
        schema18["rules"]["citation_event_recovery_trigger_max_existing_events"] = 80
        with self.assertRaisesRegex(ValueError, "citation_event_recovery_trigger_max_existing_events"):
            validate_schema(schema18)

        schema19 = _base_schema()
        schema19["rules"]["citation_event_recovery_enabled"] = "on"  # type: ignore[assignment]
        with self.assertRaisesRegex(ValueError, "citation_event_recovery_enabled"):
            validate_schema(schema19)

        schema20 = _base_schema()
        schema20["rules"]["citation_event_recovery_max_events_per_chunk"] = 0
        with self.assertRaisesRegex(ValueError, "citation_event_recovery_max_events_per_chunk"):
            validate_schema(schema20)

        schema21 = _base_schema()
        schema21["rules"]["reference_recovery_trigger_max_existing_refs"] = 500
        with self.assertRaisesRegex(ValueError, "reference_recovery_trigger_max_existing_refs"):
            validate_schema(schema21)

    def test_phase2_step_kind_map_validation(self) -> None:
        schema = _base_schema()
        schema["rules"]["phase2_critical_step_kind_map"] = {"Background": ["Definition"]}
        validate_schema(schema)

        bad_type = _base_schema()
        bad_type["rules"]["phase2_critical_step_kind_map"] = ["Background"]  # type: ignore[assignment]
        with self.assertRaisesRegex(ValueError, "phase2_critical_step_kind_map must be an object"):
            validate_schema(bad_type)

        bad_step = _base_schema()
        bad_step["rules"]["phase2_critical_step_kind_map"] = {"UnknownStep": ["Definition"]}
        with self.assertRaisesRegex(ValueError, "Unknown phase2 critical step"):
            validate_schema(bad_step)

        bad_kind = _base_schema()
        bad_kind["rules"]["phase2_critical_step_kind_map"] = {"Background": ["UnknownKind"]}
        with self.assertRaisesRegex(ValueError, "Unknown phase2 critical kind"):
            validate_schema(bad_kind)

    def test_phase2_accepts_conflict_vocab_lists(self) -> None:
        schema = _base_schema()
        schema["rules"].update(
            {
                "phase2_conflict_positive_terms_en": ["boosts", "improves"],
                "phase2_conflict_negative_terms_en": ["reduces", "worsens"],
                "phase2_conflict_stop_terms_en": ["the", "paper"],
            }
        )
        validate_schema(schema)

    def test_phase2_rejects_invalid_conflict_vocab_type(self) -> None:
        schema = _base_schema()
        schema["rules"]["phase2_conflict_positive_terms_en"] = "boosts"  # type: ignore[assignment]
        with self.assertRaisesRegex(ValueError, "phase2_conflict_positive_terms_en"):
            validate_schema(schema)

    def test_phase1_grounding_thresholds_are_validated(self) -> None:
        schema = _base_schema()
        schema["rules"].update(
            {
                "phase1_grounding_supported_overlap_min": 0.9,
                "phase1_grounding_weak_overlap_min": 0.6,
                "phase1_grounding_supported_score_substring": 0.8,
            }
        )
        validate_schema(schema)

        schema_bad = _base_schema()
        schema_bad["rules"].update(
            {
                "phase1_grounding_supported_overlap_min": 0.4,
                "phase1_grounding_weak_overlap_min": 0.6,
            }
        )
        with self.assertRaisesRegex(ValueError, "phase1_grounding_weak_overlap_min"):
            validate_schema(schema_bad)

    def test_schema_name_field_is_optional_and_validated(self) -> None:
        schema = _base_schema()
        schema["name"] = "高精度-基础版"
        validate_schema(schema)

        bad = _base_schema()
        bad["name"] = "x" * 81
        with self.assertRaisesRegex(ValueError, "name is too long"):
            validate_schema(bad)


if __name__ == "__main__":
    unittest.main()
