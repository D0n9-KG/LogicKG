from __future__ import annotations

import copy
from typing import Any, Literal


PresetId = Literal["high_precision", "balanced", "high_recall"]
PRESET_IDS: tuple[PresetId, ...] = ("high_precision", "balanced", "high_recall")

_PROMPT_KEYS: tuple[str, ...] = (
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
)

_CONFLICT_POS_EN = ["increase", "improve", "outperform", "higher", "gain", "enhance", "boost", "better"]
_CONFLICT_NEG_EN = ["decrease", "reduce", "lower", "worse", "decline", "drop", "weaken", "underperform"]
_CONFLICT_POS_ZH = ["提高", "增加", "改善", "优于", "更高", "增强"]
_CONFLICT_NEG_ZH = ["降低", "减少", "恶化", "劣于", "更低", "下降", "削弱"]
_CONFLICT_STOP_EN = [
    "the",
    "and",
    "of",
    "to",
    "in",
    "for",
    "with",
    "we",
    "our",
    "paper",
    "method",
    "result",
    "is",
    "are",
    "was",
    "were",
    "can",
    "could",
    "may",
    "might",
    "will",
    "would",
    "should",
    "which",
]
_CONFLICT_STOP_ZH = ["本文", "该文", "我们", "其", "通过", "方法", "结果", "进行"]
_DEFAULT_EXCLUDED_SECTION_TERMS = [
    "reference",
    "references",
    "bibliography",
    "further reading",
    "acknowledg",
    "funding",
    "appendix references",
    "参考文献",
    "致谢",
]


def _enabled_step_ids(schema: dict[str, Any]) -> list[str]:
    steps_all = [x for x in list(schema.get("steps") or []) if isinstance(x, dict)]
    enabled = [x for x in steps_all if bool(x.get("enabled", True))]
    out = [str(x.get("id") or "").strip() for x in enabled if str(x.get("id") or "").strip()]
    if out:
        return out
    return [str(x.get("id") or "").strip() for x in steps_all if str(x.get("id") or "").strip()]


def _enabled_kind_ids(schema: dict[str, Any]) -> list[str]:
    kinds_all = [x for x in list(schema.get("claim_kinds") or []) if isinstance(x, dict)]
    out = [
        str(x.get("id") or "").strip()
        for x in kinds_all
        if bool(x.get("enabled", True)) and str(x.get("id") or "").strip()
    ]
    if out:
        return out
    return [str(x.get("id") or "").strip() for x in kinds_all if str(x.get("id") or "").strip()]


def _pick_priority(available: list[str], preferred: list[str], *, fallback_count: int = 0) -> list[str]:
    out = [item for item in preferred if item in available]
    if out:
        return out
    if fallback_count <= 0:
        return []
    return available[: min(len(available), max(0, fallback_count))]


def _filter_known(items: list[str], allowed: list[str]) -> list[str]:
    allowed_set = set(allowed)
    out: list[str] = []
    for item in items:
        if item in allowed_set and item not in out:
            out.append(item)
    return out


def _candidate_kinds_for_step(step_id: str) -> list[str]:
    sid = str(step_id or "").strip().lower()
    if sid == "background":
        return ["Definition", "Scope", "Taxonomy", "Gap"]
    if sid == "problem":
        return ["Gap", "Assumption", "Comparison", "Definition"]
    if sid == "method":
        return ["Method", "Assumption", "Comparison", "Result"]
    if sid == "experiment":
        return ["Method", "Result", "Comparison", "Assumption"]
    if sid == "result":
        return ["Result", "Comparison", "Method"]
    if sid == "conclusion":
        return ["Conclusion", "Limitation", "FutureWork", "Gap", "Result"]
    if sid == "scope":
        return ["Scope", "Definition", "Taxonomy"]
    if sid == "taxonomy":
        return ["Taxonomy", "Definition", "Comparison", "Scope"]
    if sid == "comparison":
        return ["Comparison", "Result", "Critique", "Method"]
    if sid == "gap":
        return ["Gap", "Limitation", "FutureWork", "Critique"]
    return ["Result", "Comparison", "Method", "Definition", "Gap"]


def _build_critical_step_kind_map(
    *,
    critical_steps: list[str],
    kind_ids: list[str],
    max_kinds_per_step: int,
) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for step in critical_steps:
        preferred = _filter_known(_candidate_kinds_for_step(step), kind_ids)
        if not preferred:
            preferred = list(kind_ids[: max(1, min(2, len(kind_ids)))])
        if not preferred:
            continue
        out[step] = preferred[: max(1, max_kinds_per_step)]
    return out


def _union_from_step_kind_map(step_kind_map: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    for kinds in step_kind_map.values():
        for kind in kinds:
            k = str(kind or "").strip()
            if k and k not in out:
                out.append(k)
    return out


def _base_rule_patch(step_ids: list[str], kind_ids: list[str], paper_type: str = "research") -> dict[str, Any]:
    from app.schema_store import DEFAULT_CRITICAL_STEPS
    # 从注册表查表获取 preferred critical steps，不再用 review_like 启发式
    preferred_steps = list(DEFAULT_CRITICAL_STEPS.get(paper_type, DEFAULT_CRITICAL_STEPS["research"]))
    critical_steps = _pick_priority(step_ids, preferred_steps, fallback_count=3)
    critical_step_kind_map = _build_critical_step_kind_map(
        critical_steps=critical_steps,
        kind_ids=kind_ids,
        max_kinds_per_step=3,
    )
    return {
        "evidence_verification": "llm",
        "require_targets_for_kinds": _filter_known(["Gap", "Critique", "Limitation", "Comparison"], kind_ids),
        "phase2_critical_steps": critical_steps,
        "phase2_critical_kinds": _union_from_step_kind_map(critical_step_kind_map),
        "phase2_critical_step_kind_map": critical_step_kind_map,
        "phase2_auto_step_kind_map_enabled": True,
        "phase2_auto_step_kind_map_trigger_slots": 12,
        "phase2_auto_step_kind_map_max_kinds_per_step": 1,
        "phase1_grounding_mode": "hybrid",
        "phase1_grounding_semantic_supported_min": 0.75,
        "phase1_grounding_semantic_weak_min": 0.55,
        "phase2_conflict_mode": "hybrid",
        "phase2_conflict_semantic_threshold": 0.75,
        "phase2_conflict_candidate_max_pairs": 120,
        "phase2_quality_tier_strategy": "a1_fail_count",
        "phase2_quality_tier_yellow_max_failures": 1,
        "phase2_quality_tier_red_min_failures": 2,
        "phase2_conflict_gate_min_comparable_pairs": 4,
        "phase2_conflict_gate_min_conflict_pairs": 1,
        "phase1_filter_reference_sections": True,
        "phase1_excluded_section_terms": list(_DEFAULT_EXCLUDED_SECTION_TERMS),
        "reference_recovery_enabled": True,
        "reference_recovery_trigger_max_existing_refs": 0,
        "reference_recovery_max_refs": 180,
        "reference_recovery_doc_chars_max": 48000,
        "reference_recovery_agent_timeout_sec": 45.0,
        "citation_event_recovery_enabled": True,
        "citation_event_recovery_trigger_max_existing_events": 0,
        "citation_event_recovery_numeric_bracket_enabled": True,
        "citation_event_recovery_paren_numeric_enabled": False,
        "citation_event_recovery_author_year_enabled": True,
        "citation_event_recovery_max_events_per_chunk": 6,
        "citation_event_recovery_context_chars": 800,
        "phase1_noise_filter_enabled": True,
        "phase1_noise_filter_figure_caption_enabled": True,
        "phase1_noise_filter_pure_definition_enabled": True,
        "phase2_conflict_positive_terms_en": list(_CONFLICT_POS_EN),
        "phase2_conflict_negative_terms_en": list(_CONFLICT_NEG_EN),
        "phase2_conflict_positive_terms_zh": list(_CONFLICT_POS_ZH),
        "phase2_conflict_negative_terms_zh": list(_CONFLICT_NEG_ZH),
        "phase2_conflict_stop_terms_en": list(_CONFLICT_STOP_EN),
        "phase2_conflict_stop_terms_zh": list(_CONFLICT_STOP_ZH),
    }


def _rules_high_precision(step_ids: list[str], kind_ids: list[str], paper_type: str = "research") -> dict[str, Any]:
    patch = _base_rule_patch(step_ids, kind_ids, paper_type=paper_type)
    patch.update(
        {
            "claims_per_paper_min": 14,
            "claims_per_paper_max": 28,
            "machine_evidence_min": 1,
            "machine_evidence_max": 1,
            "logic_evidence_min": 1,
            "logic_evidence_max": 2,
            "citation_context_sentence_window": 1,
            "targets_per_claim_max": 2,
            "phase1_claim_worker_count": 2,
            "phase1_logic_chunks_max": 56,
            "phase1_logic_chunk_chars_max": 420,
            "phase1_logic_lexical_topk_min": 8,
            "phase1_logic_lexical_topk_multiplier": 3,
            "phase1_logic_evidence_weak_score_threshold": 2.4,
            "phase1_claim_chunks_max": 24,
            "phase1_claims_per_chunk_max": 2,
            "phase1_claim_batch_size": 4,
            "phase1_claim_batch_chars_max": 6400,
            "phase1_chunk_chars_max": 1400,
            "phase1_doc_chars_max": 24000,
            "phase1_evidence_verify_batch_size": 4,
            "phase1_evidence_lexical_topk": 8,
            "phase1_evidence_verify_candidates_max": 5,
            "phase1_gate_supported_ratio_min": 0.72,
            "phase1_gate_step_coverage_min": 0.55,
            "phase1_grounding_mode": "llm",
            "phase1_grounding_semantic_supported_min": 0.80,
            "phase1_grounding_semantic_weak_min": 0.62,
            "phase1_grounding_supported_overlap_min": 0.74,
            "phase1_grounding_weak_overlap_min": 0.50,
            "phase1_grounding_supported_score_substring": 0.90,
            "phase1_grounding_supported_score_overlap": 0.84,
            "phase1_grounding_weak_score": 0.58,
            "phase1_grounding_insufficient_score": 0.14,
            "phase1_grounding_unsupported_score": 0.12,
            "phase1_grounding_empty_score": 0.0,
            "phase2_gate_critical_slot_coverage_min": 0.65,
            "phase2_gate_conflict_rate_max": 0.20,
            "phase2_conflict_mode": "llm",
            "phase2_conflict_semantic_threshold": 0.80,
            "phase2_conflict_candidate_max_pairs": 180,
            "phase2_conflict_shared_tokens_min": 3,
            "phase2_conflict_samples_max": 12,
            "phase2_conflict_gate_min_comparable_pairs": 6,
            "phase2_conflict_gate_min_conflict_pairs": 2,
            "phase2_auto_step_kind_map_enabled": True,
            "phase2_auto_step_kind_map_trigger_slots": 8,
            "phase2_auto_step_kind_map_max_kinds_per_step": 1,
            "reference_recovery_trigger_max_existing_refs": 0,
            "reference_recovery_agent_timeout_sec": 30.0,
            "citation_event_recovery_trigger_max_existing_events": 0,
            "citation_event_recovery_paren_numeric_enabled": False,
            "citation_event_recovery_max_events_per_chunk": 4,
            "citation_event_recovery_context_chars": 700,
            "citation_purpose_max_contexts_per_cite": 3,
            "citation_purpose_max_context_chars": 900,
            "citation_purpose_max_cites_per_batch": 48,
            "citation_purpose_max_labels_per_cite": 2,
            "citation_purpose_fallback_score": 0.25,
        }
    )
    precision_steps = list(patch.get("phase2_critical_steps") or [])
    precision_map = _build_critical_step_kind_map(
        critical_steps=precision_steps,
        kind_ids=kind_ids,
        max_kinds_per_step=2,
    )
    patch["phase2_critical_step_kind_map"] = precision_map
    patch["phase2_critical_kinds"] = _union_from_step_kind_map(precision_map)
    return patch


def _rules_balanced(step_ids: list[str], kind_ids: list[str], paper_type: str = "research") -> dict[str, Any]:
    patch = _base_rule_patch(step_ids, kind_ids, paper_type=paper_type)
    patch.update(
        {
            "claims_per_paper_min": 22,
            "claims_per_paper_max": 44,
            "machine_evidence_min": 1,
            "machine_evidence_max": 2,
            "logic_evidence_min": 1,
            "logic_evidence_max": 2,
            "citation_context_sentence_window": 1,
            "targets_per_claim_max": 3,
            "phase1_claim_worker_count": 3,
            "phase1_logic_chunks_max": 64,
            "phase1_logic_chunk_chars_max": 460,
            "phase1_logic_lexical_topk_min": 7,
            "phase1_logic_lexical_topk_multiplier": 3,
            "phase1_logic_evidence_weak_score_threshold": 2.0,
            "phase1_claim_chunks_max": 36,
            "phase1_claims_per_chunk_max": 3,
            "phase1_claim_batch_size": 6,
            "phase1_claim_batch_chars_max": 9600,
            "phase1_chunk_chars_max": 2200,
            "phase1_doc_chars_max": 32000,
            "phase1_evidence_verify_batch_size": 6,
            "phase1_evidence_lexical_topk": 10,
            "phase1_evidence_verify_candidates_max": 6,
            "phase1_gate_supported_ratio_min": 0.55,
            "phase1_gate_step_coverage_min": 0.45,
            "phase1_grounding_mode": "hybrid",
            "phase1_grounding_semantic_supported_min": 0.75,
            "phase1_grounding_semantic_weak_min": 0.55,
            "phase1_grounding_supported_overlap_min": 0.66,
            "phase1_grounding_weak_overlap_min": 0.42,
            "phase1_grounding_supported_score_substring": 0.80,
            "phase1_grounding_supported_score_overlap": 0.74,
            "phase1_grounding_weak_score": 0.56,
            "phase1_grounding_insufficient_score": 0.18,
            "phase1_grounding_unsupported_score": 0.22,
            "phase1_grounding_empty_score": 0.0,
            "phase2_gate_critical_slot_coverage_min": 0.50,
            "phase2_gate_conflict_rate_max": 0.30,
            "phase2_conflict_mode": "hybrid",
            "phase2_conflict_semantic_threshold": 0.74,
            "phase2_conflict_candidate_max_pairs": 120,
            "phase2_conflict_shared_tokens_min": 2,
            "phase2_conflict_samples_max": 10,
            "phase2_conflict_gate_min_comparable_pairs": 4,
            "phase2_conflict_gate_min_conflict_pairs": 1,
            "phase2_auto_step_kind_map_enabled": True,
            "phase2_auto_step_kind_map_trigger_slots": 12,
            "phase2_auto_step_kind_map_max_kinds_per_step": 1,
            "reference_recovery_trigger_max_existing_refs": 2,
            "reference_recovery_agent_timeout_sec": 45.0,
            "citation_event_recovery_trigger_max_existing_events": 1,
            "citation_event_recovery_paren_numeric_enabled": False,
            "citation_event_recovery_max_events_per_chunk": 6,
            "citation_event_recovery_context_chars": 800,
            "citation_purpose_max_contexts_per_cite": 3,
            "citation_purpose_max_context_chars": 1000,
            "citation_purpose_max_cites_per_batch": 72,
            "citation_purpose_max_labels_per_cite": 3,
            "citation_purpose_fallback_score": 0.35,
        }
    )
    patch["phase2_critical_steps"] = _pick_priority(
        step_ids,
        ["Method", "Experiment", "Result", "Conclusion", "Comparison", "Gap"],
        fallback_count=2,
    )
    balanced_map = _build_critical_step_kind_map(
        critical_steps=list(patch.get("phase2_critical_steps") or []),
        kind_ids=kind_ids,
        max_kinds_per_step=3,
    )
    patch["phase2_critical_step_kind_map"] = balanced_map
    patch["phase2_critical_kinds"] = _union_from_step_kind_map(balanced_map)
    return patch


def _rules_high_recall(step_ids: list[str], kind_ids: list[str], paper_type: str = "research") -> dict[str, Any]:
    patch = _base_rule_patch(step_ids, kind_ids, paper_type=paper_type)
    patch.update(
        {
            "claims_per_paper_min": 36,
            "claims_per_paper_max": 64,
            "machine_evidence_min": 1,
            "machine_evidence_max": 3,
            "logic_evidence_min": 1,
            "logic_evidence_max": 3,
            "citation_context_sentence_window": 2,
            "targets_per_claim_max": 4,
            "phase1_claim_worker_count": 5,
            "phase1_logic_chunks_max": 120,
            "phase1_logic_chunk_chars_max": 560,
            "phase1_logic_lexical_topk_min": 8,
            "phase1_logic_lexical_topk_multiplier": 4,
            "phase1_logic_evidence_weak_score_threshold": 1.6,
            "phase1_claim_chunks_max": 72,
            "phase1_claims_per_chunk_max": 4,
            "phase1_claim_batch_size": 8,
            "phase1_claim_batch_chars_max": 12800,
            "phase1_chunk_chars_max": 2400,
            "phase1_doc_chars_max": 48000,
            "phase1_evidence_verify_batch_size": 10,
            "phase1_evidence_lexical_topk": 16,
            "phase1_evidence_verify_candidates_max": 10,
            "phase1_gate_supported_ratio_min": 0.30,
            "phase1_gate_step_coverage_min": 0.30,
            "phase1_grounding_mode": "hybrid",
            "phase1_grounding_semantic_supported_min": 0.70,
            "phase1_grounding_semantic_weak_min": 0.50,
            "phase1_grounding_supported_overlap_min": 0.56,
            "phase1_grounding_weak_overlap_min": 0.32,
            "phase1_grounding_supported_score_substring": 0.74,
            "phase1_grounding_supported_score_overlap": 0.66,
            "phase1_grounding_weak_score": 0.50,
            "phase1_grounding_insufficient_score": 0.22,
            "phase1_grounding_unsupported_score": 0.28,
            "phase1_grounding_empty_score": 0.0,
            "phase2_gate_critical_slot_coverage_min": 0.30,
            "phase2_gate_conflict_rate_max": 0.45,
            "phase2_conflict_mode": "hybrid",
            "phase2_conflict_semantic_threshold": 0.68,
            "phase2_conflict_candidate_max_pairs": 160,
            "phase2_conflict_shared_tokens_min": 2,
            "phase2_conflict_samples_max": 16,
            "phase2_conflict_gate_min_comparable_pairs": 8,
            "phase2_conflict_gate_min_conflict_pairs": 2,
            "phase2_auto_step_kind_map_enabled": True,
            "phase2_auto_step_kind_map_trigger_slots": 10,
            "phase2_auto_step_kind_map_max_kinds_per_step": 2,
            "reference_recovery_trigger_max_existing_refs": 8,
            "reference_recovery_agent_timeout_sec": 70.0,
            "citation_event_recovery_trigger_max_existing_events": 3,
            "citation_event_recovery_paren_numeric_enabled": True,
            "citation_event_recovery_max_events_per_chunk": 10,
            "citation_event_recovery_context_chars": 1000,
            "citation_purpose_max_contexts_per_cite": 4,
            "citation_purpose_max_context_chars": 1200,
            "citation_purpose_max_cites_per_batch": 100,
            "citation_purpose_max_labels_per_cite": 4,
            "citation_purpose_fallback_score": 0.45,
        }
    )
    patch["phase2_critical_steps"] = _pick_priority(
        step_ids,
        ["Method", "Result", "Comparison", "Gap", "Conclusion"],
        fallback_count=2,
    )
    recall_map = _build_critical_step_kind_map(
        critical_steps=list(patch.get("phase2_critical_steps") or []),
        kind_ids=kind_ids,
        max_kinds_per_step=2,
    )
    patch["phase2_critical_step_kind_map"] = recall_map
    patch["phase2_critical_kinds"] = _union_from_step_kind_map(recall_map)
    return patch


def _prompts_high_precision() -> dict[str, str]:
    return {
        "logic_claims_system": (
            "You are a strict scientific IE auditor.\n"
            "Return STRICT JSON only.\n"
            "Optimize for precision and faithfulness.\n"
            "Use only explicitly supported facts from paper text.\n"
            "If uncertain, omit the claim.\n"
            "Do not invent numbers, conditions, or causal direction.\n"
            "\n"
            "SCIENTIFIC VALUE (CRITICAL):\n"
            "- Extract ONLY scientific contributions, methods, findings, and conclusions.\n"
            "- DO NOT extract meta-information such as:\n"
            "  * Author names, affiliations, correspondence addresses\n"
            "  * Submission/acceptance/publication dates\n"
            "  * Funding sources, grant numbers, acknowledgments\n"
            "  * Journal names, DOIs, paper identifiers\n"
            "  * Conflict of interest statements\n"
            "  * Dataset availability, code repository links (unless core to the method)\n"
            "- If a sentence mixes scientific claim + metadata, keep the scientific claim and drop metadata fragments.\n"
            "- Keep names/URLs only when they are core identifiers of a method, model, dataset, benchmark, or tool required to express the scientific claim.\n"
            "- Focus on WHAT was discovered/proposed, not WHO/WHEN/WHERE published.\n"
            "- When encountering pure meta-information chunks, output empty claims array.\n"
            "\n"
            "Logic summaries: 2-5 full sentences per supported step.\n"
            "Claims: atomic, non-duplicate, 1-2 full sentences, one step_type each.\n"
            "claim_kinds must be 1-3 allowed kinds; confidence in [0,1]."
        ),
        "logic_claims_user_template": (
            "Extraction mode: HIGH_PRECISION.\n\n"
            "Title: {{title}}\nAuthors: {{authors}}\nYear: {{year}}\nDOI: {{doi}}\n\n"
            "Allowed step types: {{step_ids}}\n"
            "Allowed claim kinds: {{kind_ids}}\n"
            "Target claims: {{cmin}}-{{cmax}}\n\n"
            "Paper text:\n{{body}}\n\n"
            "Output JSON schema:\n"
            "{\n"
            '  "logic": {"<StepType>":{"summary":"2-5 full sentences...","confidence":0.0}},\n'
            '  "claims": [{"text":"1-2 full sentences...","confidence":0.0,"step_type":"<StepType>","claim_kinds":["KindA"]}]\n'
            "}\n"
        ),
        "evidence_pick_system": (
            "You are a strict evidence linker.\n"
            "Return STRICT JSON only.\n"
            "Pick chunk_ids that directly support each claim wording.\n"
            "Prefer exact variable/metric/number overlap.\n"
            "Avoid topical but indirect chunks.\n"
            "If direct support is absent, pick one best chunk and weak=true."
        ),
        "evidence_pick_user_template": (
            "Mode: HIGH_PRECISION evidence mapping.\n"
            "Pick {{emin}}-{{emax}} chunk_id(s) from candidates for each claim.\n"
            "If none is directly supporting, return best 1 with weak=true.\n\n"
            "Input JSON:\n{{payload_json}}\n\n"
            'Output JSON schema: { "items": [ {"claim_key":"...","evidence_chunk_ids":["c1"],"weak":false} ] }\n'
        ),
        "phase1_logic_bind_system": (
            "Bind each logic summary to supporting chunk IDs.\n"
            "Return STRICT JSON only.\n"
            "Use only provided chunk IDs.\n"
            "Prefer 1-2 strongest chunks per step.\n"
            "Set evidence_weak=true when support is indirect."
        ),
        "phase1_logic_bind_user_template": (
            "Mode: HIGH_PRECISION logic binding.\n"
            "Allowed step types: {{step_ids}}\n\n"
            "Logic summaries JSON:\n{{logic_brief_json}}\n\n"
            "Chunk catalog JSON:\n{{chunks_json}}\n\n"
            'Output JSON schema: { "items": [ {"step_type":"Background","evidence_chunk_ids":["c1"],"evidence_weak":false} ] }\n'
        ),
        "phase1_chunk_claim_extract_system": (
            "Extract atomic claims from one chunk with strict grounding.\n"
            "Return STRICT JSON only.\n"
            "\n"
            "GROUNDING:\n"
            "- Every claim must be supported by this chunk alone.\n"
            "- Skip uncertain items.\n"
            "- Keep numbers/symbols/units unchanged.\n"
            "\n"
            "EVIDENCE QUOTE (REQUIRED):\n"
            "- evidence_quote is REQUIRED for every claim.\n"
            "- evidence_quote must be copied VERBATIM from chunk text (no paraphrase, no symbol rewrite).\n"
            "- Length must be 20-220 characters.\n"
            "- If valid quote cannot be produced, DO NOT output that claim.\n"
            "\n"
            "SCIENTIFIC VALUE (CRITICAL):\n"
            "- Extract ONLY scientific contributions, methods, findings, and conclusions.\n"
            "- DO NOT extract meta-information such as:\n"
            "  * Author names, affiliations, correspondence addresses\n"
            "  * Submission/acceptance/publication dates\n"
            "  * Funding sources, grant numbers, acknowledgments\n"
            "  * Journal names, DOIs, paper identifiers\n"
            "  * Conflict of interest statements\n"
            "  * Dataset availability, code repository links (unless core to the method)\n"
            "- Focus on WHAT was discovered/proposed, not WHO/WHEN/WHERE published.\n"
            "- When encountering pure meta-information chunks, output empty claims array.\n"
        ),
        "phase1_chunk_claim_extract_user_template": (
            "Mode: HIGH_PRECISION chunk extraction.\n"
            "Allowed step types: {{step_ids}}\nAllowed claim kinds: {{kind_ids}}\nMax claims: {{max_claims}}\n\n"
            "Chunk text:\n{{chunk_text}}\n\n"
            'Output JSON schema: { "claims": [ {"text":"...","evidence_quote":"...","step_type":"Background","claim_kinds":["Definition"],"confidence":0.0} ] }\n'
        ),
        "phase1_grounding_judge_system": (
            "You are a strict claim-grounding judge for scientific IE.\n"
            "Return STRICT JSON only.\n"
            "Judge each claim against its origin chunk text.\n"
            "Prefer precision: unsupported unless evidence is explicit.\n"
            "Use labels: supported, weak, unsupported, contradicted.\n"
            "Provide confidence score in [0,1] and short reason."
        ),
        "phase1_grounding_judge_user_template": (
            "Mode: HIGH_PRECISION grounding judge.\n"
            "Supported threshold: {{supported_min}}\nWeak threshold: {{weak_min}}\n\n"
            "Input JSON:\n{{items_json}}\n\n"
            'Output JSON schema: { "items": [ {"canonical_claim_id":"...","label":"supported","score":0.0,"reason":"..."} ] }\n'
        ),
        "phase2_conflict_judge_system": (
            "You are a strict contradiction judge for scientific claims.\n"
            "Return STRICT JSON only.\n"
            "For each pair, choose contradict | not_conflict | insufficient.\n"
            "Only output contradict when both claims are comparable and genuinely opposite.\n"
            "Provide confidence score in [0,1] and concise reason."
        ),
        "phase2_conflict_judge_user_template": (
            "Mode: HIGH_PRECISION conflict judge.\n"
            "Pair count: {{pair_count}}\n\n"
            "Input JSON:\n{{pairs_json}}\n\n"
            'Output JSON schema: { "items": [ {"pair_id":"p1","label":"contradict","score":0.0,"reason":"..."} ] }\n'
        ),
        "citation_purpose_batch_system": (
            "Classify citation PURPOSE.\n"
            "Return STRICT JSON only.\n"
            "Prefer precision and conservative labels.\n"
            "Output 1-2 labels when clearly supported; otherwise Background/Summary with low score.\n"
            "Scores in [0,1]. Allowed labels: {{allowed_labels}}"
        ),
        "citation_purpose_batch_user_template": (
            "Mode: HIGH_PRECISION citation purpose classification.\n"
            "Citing paper title: {{citing_title}}\n\n"
            "Input JSON:\n{{cites_json}}\n\n"
            "Allowed labels: {{allowed_labels}}\n\n"
            "Output JSON schema:\n"
            '{ "cites": [ {"cited_paper_id":"doi:10....","labels":["MethodUse"],"scores":[0.82]} ] }\n'
        ),
        "reference_recovery_system": (
            "You are a strict reference-recovery agent for scientific markdown.\n"
            "Extract bibliography entries only from the provided text.\n"
            "Return STRICT JSON only.\n"
            "Do not fabricate references.\n"
            "If uncertain, skip the candidate."
        ),
        "reference_recovery_user_template": (
            "Mode: HIGH_PRECISION reference recovery.\n"
            "Title: {{title}}\nDOI: {{doi}}\nMax references: {{max_refs}}\n\n"
            "Markdown text:\n{{markdown_text}}\n\n"
            'Output JSON schema: { "references": [ {"raw":"..."} ] }\n'
        ),
    }


def _prompts_balanced() -> dict[str, str]:
    return {
        "logic_claims_system": (
            "You extract a paper's reasoning structure for a knowledge graph.\n"
            "Return STRICT JSON only.\n"
            "Balance precision and coverage.\n"
            "Stay faithful to text; do not invent details.\n"
            "\n"
            "SCIENTIFIC VALUE (CRITICAL):\n"
            "- Extract ONLY scientific contributions, methods, findings, and conclusions.\n"
            "- DO NOT extract meta-information such as:\n"
            "  * Author names, affiliations, correspondence addresses\n"
            "  * Submission/acceptance/publication dates\n"
            "  * Funding sources, grant numbers, acknowledgments\n"
            "  * Journal names, DOIs, paper identifiers\n"
            "  * Conflict of interest statements\n"
            "  * Dataset availability, code repository links (unless core to the method)\n"
            "- If a sentence mixes scientific claim + metadata, keep the scientific claim and drop metadata fragments.\n"
            "- Keep names/URLs only when they are core identifiers of a method, model, dataset, benchmark, or tool required to express the scientific claim.\n"
            "- Focus on WHAT was discovered/proposed, not WHO/WHEN/WHERE published.\n"
            "- When encountering pure meta-information chunks, output empty claims array.\n"
            "\n"
            "Logic summaries: 2-6 full sentences per supported step.\n"
            "Claims: atomic, non-duplicate, one step_type each, claim_kinds list from allowed kinds.\n"
            "Confidence in [0,1]."
        ),
        "logic_claims_user_template": (
            "Extraction mode: BALANCED.\n\n"
            "Title: {{title}}\nAuthors: {{authors}}\nYear: {{year}}\nDOI: {{doi}}\n\n"
            "Allowed step types: {{step_ids}}\n"
            "Allowed claim kinds: {{kind_ids}}\n"
            "Target claims: {{cmin}}-{{cmax}}\n\n"
            "Paper text:\n{{body}}\n\n"
            "Output JSON schema:\n"
            "{\n"
            '  "logic": {"<StepType>":{"summary":"2-6 full sentences...","confidence":0.0}},\n'
            '  "claims": [{"text":"1-2 full sentences...","confidence":0.0,"step_type":"<StepType>","claim_kinds":["KindA","KindB"]}]\n'
            "}\n"
        ),
        "evidence_pick_system": (
            "Pick evidence chunks for claims.\n"
            "Return STRICT JSON only.\n"
            "Prefer direct support and key metric/definition overlap.\n"
            "If support is weak, choose best available and set weak=true."
        ),
        "evidence_pick_user_template": (
            "Mode: BALANCED evidence mapping.\n"
            "Pick {{emin}}-{{emax}} chunk_id(s) from candidates per claim.\n"
            "If none strongly supports, return best 1 and weak=true.\n\n"
            "Input JSON:\n{{payload_json}}\n\n"
            'Output JSON schema: { "items": [ {"claim_key":"...","evidence_chunk_ids":["..."],"weak":false} ] }\n'
        ),
        "phase1_logic_bind_system": (
            "Bind each logic summary to supporting chunk IDs.\n"
            "Return STRICT JSON only.\n"
            "Use only provided chunk IDs.\n"
            "Keep evidence concise and relevant.\n"
            "Set evidence_weak=true when support is weak."
        ),
        "phase1_logic_bind_user_template": (
            "Mode: BALANCED logic binding.\n"
            "Allowed step types: {{step_ids}}\n\n"
            "Logic summaries JSON:\n{{logic_brief_json}}\n\n"
            "Chunk catalog JSON:\n{{chunks_json}}\n\n"
            'Output JSON schema: { "items": [ {"step_type":"Background","evidence_chunk_ids":["c1","c2"],"evidence_weak":false} ] }\n'
        ),
        "phase1_chunk_claim_extract_system": (
            "Extract atomic claims from one paper chunk.\n"
            "Return STRICT JSON only.\n"
            "\n"
            "GROUNDING:\n"
            "- Each claim must be grounded in this chunk.\n"
            "- Do not invent information outside this chunk.\n"
            "\n"
            "EVIDENCE QUOTE (REQUIRED):\n"
            "- evidence_quote is REQUIRED for every claim.\n"
            "- evidence_quote must be copied VERBATIM from chunk text (no paraphrase, no symbol rewrite).\n"
            "- Length must be 20-220 characters.\n"
            "- If valid quote cannot be produced, DO NOT output that claim.\n"
            "\n"
            "SCIENTIFIC VALUE (CRITICAL):\n"
            "- Extract ONLY scientific contributions, methods, findings, and conclusions.\n"
            "- DO NOT extract meta-information such as:\n"
            "  * Author names, affiliations, correspondence addresses\n"
            "  * Submission/acceptance/publication dates\n"
            "  * Funding sources, grant numbers, acknowledgments\n"
            "  * Journal names, DOIs, paper identifiers\n"
            "  * Conflict of interest statements\n"
            "  * Dataset availability, code repository links (unless core to the method)\n"
            "- Focus on WHAT was discovered/proposed, not WHO/WHEN/WHERE published.\n"
            "- When encountering pure meta-information chunks, output empty claims array.\n"
        ),
        "phase1_chunk_claim_extract_user_template": (
            "Mode: BALANCED chunk extraction.\n"
            "Allowed step types: {{step_ids}}\nAllowed claim kinds: {{kind_ids}}\nMax claims: {{max_claims}}\n\n"
            "Chunk text:\n{{chunk_text}}\n\n"
            'Output JSON schema: { "claims": [ {"text":"...","evidence_quote":"...","step_type":"Background","claim_kinds":["Definition"],"confidence":0.0} ] }\n'
        ),
        "phase1_grounding_judge_system": (
            "You are a claim-grounding judge for scientific IE.\n"
            "Return STRICT JSON only.\n"
            "Compare each claim against its origin chunk.\n"
            "Output supported, weak, unsupported, or contradicted with score in [0,1].\n"
            "Be faithful and concise."
        ),
        "phase1_grounding_judge_user_template": (
            "Mode: BALANCED grounding judge.\n"
            "Supported threshold: {{supported_min}}\nWeak threshold: {{weak_min}}\n\n"
            "Input JSON:\n{{items_json}}\n\n"
            'Output JSON schema: { "items": [ {"canonical_claim_id":"...","label":"supported","score":0.0,"reason":"..."} ] }\n'
        ),
        "phase2_conflict_judge_system": (
            "You are a contradiction judge for scientific claims.\n"
            "Return STRICT JSON only.\n"
            "For each pair, choose contradict | not_conflict | insufficient.\n"
            "Use contradict only when statements are semantically incompatible under comparable context.\n"
            "Output confidence in [0,1] with a short reason."
        ),
        "phase2_conflict_judge_user_template": (
            "Mode: BALANCED conflict judge.\n"
            "Pair count: {{pair_count}}\n\n"
            "Input JSON:\n{{pairs_json}}\n\n"
            'Output JSON schema: { "items": [ {"pair_id":"p1","label":"contradict","score":0.0,"reason":"..."} ] }\n'
        ),
        "citation_purpose_batch_system": (
            "Classify citation PURPOSE in mechanics paper.\n"
            "Return STRICT JSON only.\n"
            "Output 1-3 labels from allowed list with scores in [0,1].\n"
            "If weak evidence, use Background/Summary with lower confidence.\n"
            "Allowed labels: {{allowed_labels}}"
        ),
        "citation_purpose_batch_user_template": (
            "Mode: BALANCED citation purpose classification.\n"
            "Citing paper title: {{citing_title}}\n\n"
            "Input JSON:\n{{cites_json}}\n\n"
            "Allowed labels: {{allowed_labels}}\n\n"
            'Output JSON schema: { "cites": [ {"cited_paper_id":"doi:10....","labels":["MethodUse"],"scores":[0.72]} ] }\n'
        ),
        "reference_recovery_system": (
            "You recover bibliography entries from a scientific markdown document.\n"
            "Return STRICT JSON only.\n"
            "Extract only entries that are explicitly present.\n"
            "Do not invent references."
        ),
        "reference_recovery_user_template": (
            "Mode: BALANCED reference recovery.\n"
            "Title: {{title}}\nDOI: {{doi}}\nMax references: {{max_refs}}\n\n"
            "Markdown text:\n{{markdown_text}}\n\n"
            'Output JSON schema: { "references": [ {"raw":"..."} ] }\n'
        ),
    }


def _prompts_high_recall() -> dict[str, str]:
    return {
        "logic_claims_system": (
            "You are a comprehensive scientific extractor for a knowledge graph.\n"
            "Return STRICT JSON only.\n"
            "Maximize useful coverage while staying grounded in text.\n"
            "Capture primary and secondary supported findings.\n"
            "Do not hallucinate unsupported facts.\n"
            "\n"
            "SCIENTIFIC VALUE (CRITICAL):\n"
            "- Extract ONLY scientific contributions, methods, findings, and conclusions.\n"
            "- DO NOT extract meta-information such as:\n"
            "  * Author names, affiliations, correspondence addresses\n"
            "  * Submission/acceptance/publication dates\n"
            "  * Funding sources, grant numbers, acknowledgments\n"
            "  * Journal names, DOIs, paper identifiers\n"
            "  * Conflict of interest statements\n"
            "  * Dataset availability, code repository links (unless core to the method)\n"
            "- If a sentence mixes scientific claim + metadata, keep the scientific claim and drop metadata fragments.\n"
            "- Keep names/URLs only when they are core identifiers of a method, model, dataset, benchmark, or tool required to express the scientific claim.\n"
            "- Focus on WHAT was discovered/proposed, not WHO/WHEN/WHERE published.\n"
            "- When encountering pure meta-information chunks, output empty claims array.\n"
            "\n"
            "Logic summaries: 2-7 full sentences per supported step.\n"
            "Claims: atomic, diverse, one step_type each, claim_kinds from allowed list.\n"
            "Use confidence in [0,1] to reflect uncertainty."
        ),
        "logic_claims_user_template": (
            "Extraction mode: HIGH_RECALL.\n\n"
            "Title: {{title}}\nAuthors: {{authors}}\nYear: {{year}}\nDOI: {{doi}}\n\n"
            "Allowed step types: {{step_ids}}\n"
            "Allowed claim kinds: {{kind_ids}}\n"
            "Target claims: {{cmin}}-{{cmax}}\n\n"
            "Paper text:\n{{body}}\n\n"
            "Output JSON schema:\n"
            "{\n"
            '  "logic": {"<StepType>":{"summary":"2-7 full sentences...","confidence":0.0}},\n'
            '  "claims": [{"text":"1-2 full sentences...","confidence":0.0,"step_type":"<StepType>","claim_kinds":["KindA"]}]\n'
            "}\n"
        ),
        "evidence_pick_system": (
            "Pick evidence chunks for claims with high recall.\n"
            "Return STRICT JSON only.\n"
            "Use only candidate chunk_ids.\n"
            "Prefer direct support but keep complementary supporting chunks when useful.\n"
            "Set weak=true when support is indirect."
        ),
        "evidence_pick_user_template": (
            "Mode: HIGH_RECALL evidence mapping.\n"
            "Pick {{emin}}-{{emax}} chunk_id(s) from candidates per claim.\n"
            "If support is weak, still pick best available and set weak=true.\n\n"
            "Input JSON:\n{{payload_json}}\n\n"
            'Output JSON schema: { "items": [ {"claim_key":"...","evidence_chunk_ids":["..."],"weak":false} ] }\n'
        ),
        "phase1_logic_bind_system": (
            "Bind each logic summary to supporting chunk IDs with broad coverage.\n"
            "Return STRICT JSON only.\n"
            "Use only provided chunk IDs.\n"
            "When possible, cover setup/method/result facets.\n"
            "Set evidence_weak=true if support is weak."
        ),
        "phase1_logic_bind_user_template": (
            "Mode: HIGH_RECALL logic binding.\n"
            "Allowed step types: {{step_ids}}\n\n"
            "Logic summaries JSON:\n{{logic_brief_json}}\n\n"
            "Chunk catalog JSON:\n{{chunks_json}}\n\n"
            'Output JSON schema: { "items": [ {"step_type":"Background","evidence_chunk_ids":["c1","c2","c3"],"evidence_weak":false} ] }\n'
        ),
        "phase1_chunk_claim_extract_system": (
            "Extract atomic claims from one chunk with high recall.\n"
            "Return STRICT JSON only.\n"
            "\n"
            "GROUNDING:\n"
            "- Claims must remain grounded in this chunk.\n"
            "- Include secondary findings, conditions, and caveats when text supports them.\n"
            "- Avoid exact duplicates.\n"
            "\n"
            "EVIDENCE QUOTE (REQUIRED):\n"
            "- evidence_quote is REQUIRED for every claim.\n"
            "- evidence_quote must be copied VERBATIM from chunk text (no paraphrase, no symbol rewrite).\n"
            "- Length must be 20-220 characters.\n"
            "- If valid quote cannot be produced, DO NOT output that claim.\n"
            "\n"
            "SCIENTIFIC VALUE (CRITICAL):\n"
            "- Extract ONLY scientific contributions, methods, findings, and conclusions.\n"
            "- DO NOT extract meta-information such as:\n"
            "  * Author names, affiliations, correspondence addresses\n"
            "  * Submission/acceptance/publication dates\n"
            "  * Funding sources, grant numbers, acknowledgments\n"
            "  * Journal names, DOIs, paper identifiers\n"
            "  * Conflict of interest statements\n"
            "  * Dataset availability, code repository links (unless core to the method)\n"
            "- Focus on WHAT was discovered/proposed, not WHO/WHEN/WHERE published.\n"
            "- When encountering pure meta-information chunks, output empty claims array.\n"
        ),
        "phase1_chunk_claim_extract_user_template": (
            "Mode: HIGH_RECALL chunk extraction.\n"
            "Allowed step types: {{step_ids}}\nAllowed claim kinds: {{kind_ids}}\nMax claims: {{max_claims}}\n\n"
            "Chunk text:\n{{chunk_text}}\n\n"
            'Output JSON schema: { "claims": [ {"text":"...","evidence_quote":"...","step_type":"Background","claim_kinds":["Definition","Result"],"confidence":0.0} ] }\n'
        ),
        "phase1_grounding_judge_system": (
            "You are a high-recall claim-grounding judge for scientific IE.\n"
            "Return STRICT JSON only.\n"
            "Compare each claim and origin chunk; keep sensitivity to partial support.\n"
            "Output supported, weak, unsupported, or contradicted with score in [0,1]."
        ),
        "phase1_grounding_judge_user_template": (
            "Mode: HIGH_RECALL grounding judge.\n"
            "Supported threshold: {{supported_min}}\nWeak threshold: {{weak_min}}\n\n"
            "Input JSON:\n{{items_json}}\n\n"
            'Output JSON schema: { "items": [ {"canonical_claim_id":"...","label":"supported","score":0.0,"reason":"..."} ] }\n'
        ),
        "phase2_conflict_judge_system": (
            "You are a contradiction judge for scientific claims with recall-friendly policy.\n"
            "Return STRICT JSON only.\n"
            "For each pair, choose contradict | not_conflict | insufficient.\n"
            "Label contradict only when semantic opposition is clear.\n"
            "Output confidence in [0,1] and concise reason."
        ),
        "phase2_conflict_judge_user_template": (
            "Mode: HIGH_RECALL conflict judge.\n"
            "Pair count: {{pair_count}}\n\n"
            "Input JSON:\n{{pairs_json}}\n\n"
            'Output JSON schema: { "items": [ {"pair_id":"p1","label":"contradict","score":0.0,"reason":"..."} ] }\n'
        ),
        "citation_purpose_batch_system": (
            "Classify citation PURPOSE with higher recall.\n"
            "Return STRICT JSON only.\n"
            "Output 1-4 labels when contexts show multiple plausible roles.\n"
            "Scores in [0,1]; keep lower confidence for weak evidence.\n"
            "Allowed labels: {{allowed_labels}}"
        ),
        "citation_purpose_batch_user_template": (
            "Mode: HIGH_RECALL citation purpose classification.\n"
            "Citing paper title: {{citing_title}}\n\n"
            "Input JSON:\n{{cites_json}}\n\n"
            "Allowed labels: {{allowed_labels}}\n\n"
            'Output JSON schema: { "cites": [ {"cited_paper_id":"doi:10....","labels":["Background","MethodUse"],"scores":[0.58,0.51]} ] }\n'
        ),
        "reference_recovery_system": (
            "You are a high-recall bibliography recovery agent for scientific markdown.\n"
            "Return STRICT JSON only.\n"
            "Capture as many valid reference entries as possible while remaining grounded in text.\n"
            "Do not fabricate entries."
        ),
        "reference_recovery_user_template": (
            "Mode: HIGH_RECALL reference recovery.\n"
            "Title: {{title}}\nDOI: {{doi}}\nMax references: {{max_refs}}\n\n"
            "Markdown text:\n{{markdown_text}}\n\n"
            'Output JSON schema: { "references": [ {"raw":"..."} ] }\n'
        ),
    }


def _prompts_for(preset_id: PresetId) -> dict[str, str]:
    if preset_id == "high_precision":
        return _prompts_high_precision()
    if preset_id == "high_recall":
        return _prompts_high_recall()
    return _prompts_balanced()


def _rules_for(preset_id: PresetId, *, step_ids: list[str], kind_ids: list[str], paper_type: str = "research") -> dict[str, Any]:
    if preset_id == "high_precision":
        return _rules_high_precision(step_ids, kind_ids, paper_type=paper_type)
    if preset_id == "high_recall":
        return _rules_high_recall(step_ids, kind_ids, paper_type=paper_type)
    return _rules_balanced(step_ids, kind_ids, paper_type=paper_type)


def list_schema_presets() -> list[dict[str, Any]]:
    return [
        {
            "id": "high_precision",
            "label_zh": "高精度",
            "label_en": "High Precision",
            "summary_zh": "更严格的证据与门禁阈值，优先保证可溯源和低冲突。",
            "focus_zh": "准确性、可解释性、冲突控制",
            "use_case_zh": "高价值论文入库、结论可信度要求高的场景",
            "prompt_keys": list(_PROMPT_KEYS),
        },
        {
            "id": "balanced",
            "label_zh": "均衡",
            "label_en": "Balanced",
            "summary_zh": "在抽取覆盖率与准确性之间取得平衡，适合大多数常规批处理。",
            "focus_zh": "稳定产出、质量与覆盖折中",
            "use_case_zh": "默认生产流程、持续迭代调参",
            "prompt_keys": list(_PROMPT_KEYS),
        },
        {
            "id": "high_recall",
            "label_zh": "高召回",
            "label_en": "High Recall",
            "summary_zh": "扩大候选与抽取范围，尽可能捕获更多可用要点，再依赖门禁过滤。",
            "focus_zh": "覆盖率、信息丰富度、候选扩展",
            "use_case_zh": "探索性分析、前期知识发现与样本补全",
            "prompt_keys": list(_PROMPT_KEYS),
        },
    ]


def apply_schema_preset(schema: dict[str, Any], *, preset_id: PresetId) -> dict[str, Any]:
    if preset_id not in PRESET_IDS:
        raise ValueError(f"Unknown schema preset: {preset_id!r}")
    out = copy.deepcopy(schema)
    step_ids = _enabled_step_ids(out)
    kind_ids = _enabled_kind_ids(out)
    paper_type = str(out.get("paper_type") or "research").strip().lower()

    rules = dict(out.get("rules") or {})
    rules.update(_rules_for(preset_id, step_ids=step_ids, kind_ids=kind_ids, paper_type=paper_type))
    rules["phase2_critical_steps"] = _filter_known(list(rules.get("phase2_critical_steps") or []), step_ids)
    rules["phase2_critical_kinds"] = _filter_known(list(rules.get("phase2_critical_kinds") or []), kind_ids)
    raw_map = rules.get("phase2_critical_step_kind_map") or {}
    clean_map: dict[str, list[str]] = {}
    if isinstance(raw_map, dict):
        for step in step_ids:
            kinds = raw_map.get(step)
            if not isinstance(kinds, list):
                continue
            keep = _filter_known([str(x).strip() for x in kinds if str(x).strip()], kind_ids)
            if keep:
                clean_map[step] = keep
    rules["phase2_critical_step_kind_map"] = clean_map
    if clean_map:
        rules["phase2_critical_steps"] = list(clean_map.keys())
        rules["phase2_critical_kinds"] = _union_from_step_kind_map(clean_map)
    rules["phase1_excluded_section_terms"] = [
        str(x).strip()
        for x in (rules.get("phase1_excluded_section_terms") or [])
        if str(x).strip()
    ]
    rules["require_targets_for_kinds"] = _filter_known(list(rules.get("require_targets_for_kinds") or []), kind_ids)
    out["rules"] = rules

    prompts = dict(out.get("prompts") or {})
    preset_prompts = _prompts_for(preset_id)
    for key in _PROMPT_KEYS:
        prompts[key] = str(preset_prompts.get(key) or "").strip()
    out["prompts"] = prompts
    return out


__all__ = ["PresetId", "PRESET_IDS", "apply_schema_preset", "list_schema_presets"]
