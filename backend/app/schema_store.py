from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from app.settings import settings


PaperType = Literal["research", "review", "software", "theoretical", "case_study"]
PAPER_TYPES: tuple[str, ...] = ("research", "review", "software", "theoretical", "case_study")
_PAPER_TYPE_SET: frozenset[str] = frozenset(PAPER_TYPES)

# 每种论文类型的默认 critical steps（用于 schema 预填充和 _base_rule_patch 查表）
DEFAULT_CRITICAL_STEPS: dict[str, tuple[str, ...]] = {
    "research": ("Problem", "Method", "Experiment", "Result", "Conclusion"),
    "review": ("Scope", "Taxonomy", "Comparison", "Gap", "Conclusion"),
    "software": ("Problem", "Method", "Result", "Conclusion"),
    "theoretical": ("Problem", "Method", "Result", "Conclusion"),
    "case_study": ("Background", "Problem", "Method", "Result", "Conclusion"),
}


def coerce_paper_type(value: Any) -> PaperType | None:
    """尝试将任意值转为合法 PaperType，失败返回 None。"""
    raw = str(value or "").strip().lower()
    if raw in _PAPER_TYPE_SET:
        return cast(PaperType, raw)
    return None


def normalize_paper_type(value: Any, *, default: PaperType = "research") -> PaperType:
    """将任意值转为合法 PaperType，无效时返回 default。"""
    return coerce_paper_type(value) or default

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,47}$")
_PROMPT_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")


@dataclass(frozen=True)
class SchemaVersionInfo:
    paper_type: PaperType
    version: int
    path: Path
    name: str = ""


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _schemas_root() -> Path:
    # backend/storage/schemas
    root = _backend_root()
    p = root / settings.storage_dir / "schemas"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _paper_type_dir(paper_type: PaperType) -> Path:
    d = _schemas_root() / paper_type
    d.mkdir(parents=True, exist_ok=True)
    return d


def _active_path(paper_type: PaperType) -> Path:
    return _paper_type_dir(paper_type) / "active.json"


def _version_path(paper_type: PaperType, version: int) -> Path:
    return _paper_type_dir(paper_type) / f"v{int(version)}.json"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _default_schema(paper_type: PaperType) -> dict[str, Any]:
    # NOTE: IDs are stable ASCII slugs. Labels are editable.
    if paper_type == "review":
        # Review papers: default to a "review-ish" chain but keep it editable.
        steps = [
            {"id": "Background", "label_zh": "背景", "label_en": "Background", "enabled": True, "order": 0},
            {"id": "Scope", "label_zh": "范围/定义", "label_en": "Scope", "enabled": True, "order": 1},
            {"id": "Taxonomy", "label_zh": "分类/框架", "label_en": "Taxonomy", "enabled": True, "order": 2},
            {"id": "Comparison", "label_zh": "对比/综述", "label_en": "Comparison", "enabled": True, "order": 3},
            {"id": "Gap", "label_zh": "研究缺口", "label_en": "Gap", "enabled": True, "order": 4},
            {"id": "Conclusion", "label_zh": "总结与展望", "label_en": "Conclusion", "enabled": True, "order": 5},
        ]
    else:
        # research / software / theoretical / case_study 共享 research steps
        steps = [
            {"id": "Background", "label_zh": "背景", "label_en": "Background", "enabled": True, "order": 0},
            {"id": "Problem", "label_zh": "问题", "label_en": "Problem", "enabled": True, "order": 1},
            {"id": "Method", "label_zh": "方法", "label_en": "Method", "enabled": True, "order": 2},
            {"id": "Experiment", "label_zh": "实验", "label_en": "Experiment", "enabled": True, "order": 3},
            {"id": "Result", "label_zh": "结果", "label_en": "Result", "enabled": True, "order": 4},
            {"id": "Conclusion", "label_zh": "结论", "label_en": "Conclusion", "enabled": True, "order": 5},
        ]

    claim_kinds = [
        {"id": "Definition", "label_zh": "定义", "label_en": "Definition", "enabled": True},
        {"id": "Method", "label_zh": "方法", "label_en": "Method", "enabled": True},
        {"id": "Result", "label_zh": "结果", "label_en": "Result", "enabled": True},
        {"id": "Conclusion", "label_zh": "结论", "label_en": "Conclusion", "enabled": True},
        {"id": "Gap", "label_zh": "缺口", "label_en": "Gap", "enabled": True},
        {"id": "Critique", "label_zh": "批判", "label_en": "Critique", "enabled": True},
        {"id": "Limitation", "label_zh": "局限", "label_en": "Limitation", "enabled": True},
        {"id": "FutureWork", "label_zh": "未来工作", "label_en": "FutureWork", "enabled": True},
        {"id": "Comparison", "label_zh": "对比", "label_en": "Comparison", "enabled": True},
        {"id": "Assumption", "label_zh": "假设", "label_en": "Assumption", "enabled": True},
        {"id": "Scope", "label_zh": "范围", "label_en": "Scope", "enabled": True},
        {"id": "Taxonomy", "label_zh": "分类", "label_en": "Taxonomy", "enabled": True},
    ]

    return {
        "paper_type": paper_type,
        "version": 1,
        "name": "默认配置",
        "steps": steps,
        "claim_kinds": claim_kinds,
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
            "phase1_claim_worker_count": 3,
            "phase1_logic_chunks_max": 56,
            "phase1_logic_chunk_chars_max": 420,
            "phase1_logic_lexical_topk_min": 6,
            "phase1_logic_lexical_topk_multiplier": 3,
            "phase1_logic_evidence_weak_score_threshold": 2.0,
            "phase1_claim_chunks_max": 36,
            "phase1_claims_per_chunk_max": 3,
            "phase1_chunk_chars_max": 1800,
            "phase1_doc_chars_max": 18000,
            "phase1_filter_reference_sections": True,
            "phase1_excluded_section_terms": [],
            "phase1_evidence_verify_batch_size": 6,
            "phase1_evidence_lexical_topk": 10,
            "phase1_evidence_verify_candidates_max": 6,
            "phase1_gate_supported_ratio_min": 0.5,
            "phase1_gate_step_coverage_min": 0.4,
            "phase1_grounding_mode": "lexical",
            "phase1_grounding_semantic_supported_min": 0.75,
            "phase1_grounding_semantic_weak_min": 0.55,
            "phase1_grounding_supported_overlap_min": 0.65,
            "phase1_grounding_weak_overlap_min": 0.42,
            "phase1_grounding_supported_score_substring": 0.78,
            "phase1_grounding_supported_score_overlap": 0.72,
            "phase1_grounding_weak_score": 0.55,
            "phase1_grounding_insufficient_score": 0.18,
            "phase1_grounding_unsupported_score": 0.22,
            "phase1_grounding_empty_score": 0.0,
            "phase2_critical_steps": list(DEFAULT_CRITICAL_STEPS.get(paper_type, DEFAULT_CRITICAL_STEPS["research"])),
            "phase2_critical_kinds": [],
            "phase2_critical_step_kind_map": {},
            "phase2_auto_step_kind_map_enabled": True,
            "phase2_auto_step_kind_map_trigger_slots": 12,
            "phase2_auto_step_kind_map_max_kinds_per_step": 1,
            "phase2_gate_critical_slot_coverage_min": 0.4,
            # Backward-compatible default: disabled unless schema explicitly enables it.
            "phase2_gate_step_coverage_bypass_excellent": False,
            "phase2_gate_logic_steps_coverage_min": 0.83,
            "phase2_gate_logic_steps_guard_validated": True,
            "phase2_gate_critical_slot_bypass_min_coverage": 0.35,
            "phase2_gate_critical_slot_bypass_min_critical_steps_with_claims": 2,
            "phase2_gate_critical_slot_bypass_require_result_or_conclusion": True,
            "phase2_gate_critical_slot_bypass_min_result_like_claims": 1,
            "phase2_gate_critical_slot_bypass_min_result_like_ratio": 0.0,
            "phase2_gate_step_bypass_min_critical_steps_with_claims": 2,
            "phase2_gate_step_bypass_require_non_method_claim": True,
            "phase2_gate_base_min_non_method_critical_claims": 0,
            "phase2_gate_base_min_result_like_claims": 0,
            "phase2_gate_base_min_result_like_ratio": 0.0,
            "phase2_gate_conflict_rate_max": 0.35,
            "phase2_conflict_mode": "lexical",
            "phase2_conflict_semantic_threshold": 0.75,
            "phase2_conflict_candidate_max_pairs": 120,
            "phase2_conflict_shared_tokens_min": 2,
            "phase2_conflict_samples_max": 8,
            "phase2_conflict_gate_min_comparable_pairs": 3,
            "phase2_conflict_gate_min_conflict_pairs": 1,
            "phase2_quality_tier_strategy": "a1_fail_count",
            "phase2_quality_tier_yellow_max_failures": 1,
            "phase2_quality_tier_red_min_failures": 2,
            "phase2_conflict_positive_terms_en": [],
            "phase2_conflict_negative_terms_en": [],
            "phase2_conflict_positive_terms_zh": [],
            "phase2_conflict_negative_terms_zh": [],
            "phase2_conflict_stop_terms_en": [],
            "phase2_conflict_stop_terms_zh": [],
            "citation_purpose_max_contexts_per_cite": 3,
            "citation_purpose_max_context_chars": 900,
            "citation_purpose_max_cites_per_batch": 60,
            "citation_purpose_max_labels_per_cite": 3,
            "citation_purpose_fallback_score": 0.4,
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
        },
    }


def validate_schema(schema: dict[str, Any]) -> None:
    if not isinstance(schema, dict):
        raise ValueError("schema must be an object")
    paper_type = schema.get("paper_type")
    if paper_type not in _PAPER_TYPE_SET:
        raise ValueError(f"paper_type must be one of: {', '.join(PAPER_TYPES)}")
    if not isinstance(schema.get("steps"), list) or not schema["steps"]:
        raise ValueError("steps must be a non-empty list")
    if not isinstance(schema.get("claim_kinds"), list) or not schema["claim_kinds"]:
        raise ValueError("claim_kinds must be a non-empty list")
    name = schema.get("name")
    if name is not None:
        if not isinstance(name, str):
            raise ValueError("name must be a string")
        name = name.strip()
        if len(name) > 80:
            raise ValueError("name is too long (max 80 chars)")

    step_ids: set[str] = set()
    for s in schema["steps"]:
        if not isinstance(s, dict):
            raise ValueError("steps[*] must be objects")
        sid = str(s.get("id") or "")
        if not _ID_RE.match(sid):
            raise ValueError(f"Invalid step id: {sid!r}")
        if sid in step_ids:
            raise ValueError(f"Duplicate step id: {sid}")
        step_ids.add(sid)

    kind_ids: set[str] = set()
    for k in schema["claim_kinds"]:
        if not isinstance(k, dict):
            raise ValueError("claim_kinds[*] must be objects")
        kid = str(k.get("id") or "")
        if not _ID_RE.match(kid):
            raise ValueError(f"Invalid claim kind id: {kid!r}")
        if kid in kind_ids:
            raise ValueError(f"Duplicate claim kind id: {kid}")
        kind_ids.add(kid)

    rules = schema.get("rules") or {}
    if not isinstance(rules, dict):
        raise ValueError("rules must be an object")
    cmin = int(rules.get("claims_per_paper_min") or 0)
    cmax = int(rules.get("claims_per_paper_max") or 0)
    if cmin < 1 or cmax < cmin:
        raise ValueError("Invalid claims_per_paper_min/max")
    emin = int(rules.get("machine_evidence_min") or 0)
    emax = int(rules.get("machine_evidence_max") or 0)
    if emin < 0 or emax < emin or emax > 6:
        raise ValueError("Invalid machine_evidence_min/max")
    lmin = int(rules.get("logic_evidence_min") or 0)
    lmax = int(rules.get("logic_evidence_max") or 0)
    if lmin < 0 or lmax < lmin or lmax > 8:
        raise ValueError("Invalid logic_evidence_min/max")
    vw = int(rules.get("citation_context_sentence_window") or 1)
    if vw < 0 or vw > 3:
        raise ValueError("Invalid citation_context_sentence_window")
    tp = int(rules.get("targets_per_claim_max") or 0)
    if tp < 0 or tp > 5:
        raise ValueError("Invalid targets_per_claim_max")
    wcnt = int(rules.get("phase1_claim_worker_count") or 3)
    if wcnt < 1 or wcnt > 16:
        raise ValueError("Invalid phase1_claim_worker_count")
    logic_chunks = int(rules.get("phase1_logic_chunks_max") or 56)
    if logic_chunks < 8 or logic_chunks > 300:
        raise ValueError("Invalid phase1_logic_chunks_max")
    logic_chunk_chars = int(rules.get("phase1_logic_chunk_chars_max") or 420)
    if logic_chunk_chars < 120 or logic_chunk_chars > 3000:
        raise ValueError("Invalid phase1_logic_chunk_chars_max")
    logic_topk_min = int(rules.get("phase1_logic_lexical_topk_min", 6))
    if logic_topk_min < 1 or logic_topk_min > 64:
        raise ValueError("Invalid phase1_logic_lexical_topk_min")
    logic_topk_multiplier = int(rules.get("phase1_logic_lexical_topk_multiplier", 3))
    if logic_topk_multiplier < 1 or logic_topk_multiplier > 12:
        raise ValueError("Invalid phase1_logic_lexical_topk_multiplier")
    weak_score_threshold = float(rules.get("phase1_logic_evidence_weak_score_threshold", 2.0))
    if weak_score_threshold < 0.0 or weak_score_threshold > 20.0:
        raise ValueError("Invalid phase1_logic_evidence_weak_score_threshold")
    cmax_chunks = int(rules.get("phase1_claim_chunks_max") or 36)
    if cmax_chunks < 1 or cmax_chunks > 9999:
        raise ValueError("Invalid phase1_claim_chunks_max")
    cmax_per_chunk = int(rules.get("phase1_claims_per_chunk_max") or 3)
    if cmax_per_chunk < 1 or cmax_per_chunk > 12:
        raise ValueError("Invalid phase1_claims_per_chunk_max")
    chunk_chars = int(rules.get("phase1_chunk_chars_max") or 1800)
    if chunk_chars < 200 or chunk_chars > 20000:
        raise ValueError("Invalid phase1_chunk_chars_max")
    doc_chars = int(rules.get("phase1_doc_chars_max") or 18000)
    if doc_chars < 2000 or doc_chars > 120000:
        raise ValueError("Invalid phase1_doc_chars_max")
    filter_reference_sections = rules.get("phase1_filter_reference_sections", True)
    if not isinstance(filter_reference_sections, bool):
        raise ValueError("phase1_filter_reference_sections must be boolean")
    excluded_section_terms = rules.get("phase1_excluded_section_terms", [])
    if excluded_section_terms is None:
        excluded_section_terms = []
    if not isinstance(excluded_section_terms, list):
        raise ValueError("phase1_excluded_section_terms must be a list")
    if len(excluded_section_terms) > 200:
        raise ValueError("phase1_excluded_section_terms is too long")
    for item in excluded_section_terms:
        s = str(item or "").strip()
        if not s:
            continue
        if len(s) > 80:
            raise ValueError("phase1_excluded_section_terms contains too long term")
    evidence_batch = int(rules.get("phase1_evidence_verify_batch_size", 6))
    if evidence_batch < 1 or evidence_batch > 32:
        raise ValueError("Invalid phase1_evidence_verify_batch_size")
    evidence_topk = int(rules.get("phase1_evidence_lexical_topk", 10))
    if evidence_topk < 1 or evidence_topk > 64:
        raise ValueError("Invalid phase1_evidence_lexical_topk")
    evidence_verify_candidates = int(rules.get("phase1_evidence_verify_candidates_max", 6))
    if evidence_verify_candidates < 1 or evidence_verify_candidates > 16:
        raise ValueError("Invalid phase1_evidence_verify_candidates_max")
    gate_supported_raw = rules.get("phase1_gate_supported_ratio_min", 0.5)
    gate_supported = float(gate_supported_raw)
    if gate_supported < 0.0 or gate_supported > 1.0:
        raise ValueError("Invalid phase1_gate_supported_ratio_min")
    gate_coverage_raw = rules.get("phase1_gate_step_coverage_min", 0.4)
    gate_coverage = float(gate_coverage_raw)
    if gate_coverage < 0.0 or gate_coverage > 1.0:
        raise ValueError("Invalid phase1_gate_step_coverage_min")
    grounding_mode = str(rules.get("phase1_grounding_mode", "lexical") or "").strip().lower()
    if grounding_mode not in {"skip", "lexical", "hybrid", "llm"}:
        raise ValueError("Invalid phase1_grounding_mode")
    grounding_semantic_supported_min = float(rules.get("phase1_grounding_semantic_supported_min", 0.75))
    if grounding_semantic_supported_min < 0.0 or grounding_semantic_supported_min > 1.0:
        raise ValueError("Invalid phase1_grounding_semantic_supported_min")
    grounding_semantic_weak_min = float(rules.get("phase1_grounding_semantic_weak_min", 0.55))
    if grounding_semantic_weak_min < 0.0 or grounding_semantic_weak_min > 1.0:
        raise ValueError("Invalid phase1_grounding_semantic_weak_min")
    if grounding_semantic_weak_min > grounding_semantic_supported_min:
        raise ValueError("phase1_grounding_semantic_weak_min must be <= phase1_grounding_semantic_supported_min")
    grounding_supported_overlap = float(rules.get("phase1_grounding_supported_overlap_min", 0.65))
    if grounding_supported_overlap < 0.0 or grounding_supported_overlap > 1.0:
        raise ValueError("Invalid phase1_grounding_supported_overlap_min")
    grounding_weak_overlap = float(rules.get("phase1_grounding_weak_overlap_min", 0.42))
    if grounding_weak_overlap < 0.0 or grounding_weak_overlap > 1.0:
        raise ValueError("Invalid phase1_grounding_weak_overlap_min")
    if grounding_weak_overlap > grounding_supported_overlap:
        raise ValueError("phase1_grounding_weak_overlap_min must be <= phase1_grounding_supported_overlap_min")
    for key in (
        "phase1_grounding_supported_score_substring",
        "phase1_grounding_supported_score_overlap",
        "phase1_grounding_weak_score",
        "phase1_grounding_insufficient_score",
        "phase1_grounding_unsupported_score",
        "phase1_grounding_empty_score",
    ):
        score = float(rules.get(key, 0.5))
        if score < 0.0 or score > 1.0:
            raise ValueError(f"Invalid {key}")
    critical_steps = rules.get("phase2_critical_steps")
    if critical_steps is not None:
        if not isinstance(critical_steps, list):
            raise ValueError("phase2_critical_steps must be a list")
        for sid in critical_steps:
            s = str(sid or "").strip()
            if s and s not in step_ids:
                raise ValueError(f"Unknown phase2 critical step: {s}")
    critical_kinds = rules.get("phase2_critical_kinds")
    if critical_kinds is not None:
        if not isinstance(critical_kinds, list):
            raise ValueError("phase2_critical_kinds must be a list")
        for kid in critical_kinds:
            k = str(kid or "").strip()
            if k and k not in kind_ids:
                raise ValueError(f"Unknown phase2 critical kind: {k}")
    critical_step_kind_map = rules.get("phase2_critical_step_kind_map")
    if critical_step_kind_map is not None:
        if not isinstance(critical_step_kind_map, dict):
            raise ValueError("phase2_critical_step_kind_map must be an object")
        for sid_raw, kinds_raw in critical_step_kind_map.items():
            sid = str(sid_raw or "").strip()
            if not sid:
                continue
            if sid not in step_ids:
                raise ValueError(f"Unknown phase2 critical step: {sid}")
            if not isinstance(kinds_raw, list):
                raise ValueError(f"phase2_critical_step_kind_map[{sid!r}] must be a list")
            for kid in kinds_raw:
                k = str(kid or "").strip()
                if k and k not in kind_ids:
                    raise ValueError(f"Unknown phase2 critical kind: {k}")
    auto_step_kind_map_enabled = rules.get("phase2_auto_step_kind_map_enabled", True)
    if not isinstance(auto_step_kind_map_enabled, bool):
        raise ValueError("phase2_auto_step_kind_map_enabled must be boolean")
    auto_step_kind_map_trigger_slots = int(rules.get("phase2_auto_step_kind_map_trigger_slots", 12))
    if auto_step_kind_map_trigger_slots < 1 or auto_step_kind_map_trigger_slots > 200:
        raise ValueError("Invalid phase2_auto_step_kind_map_trigger_slots")
    auto_step_kind_map_max_kinds = int(rules.get("phase2_auto_step_kind_map_max_kinds_per_step", 1))
    if auto_step_kind_map_max_kinds < 1 or auto_step_kind_map_max_kinds > 6:
        raise ValueError("Invalid phase2_auto_step_kind_map_max_kinds_per_step")
    gate_critical = rules.get("phase2_gate_critical_slot_coverage_min", 0.4)
    try:
        gate_critical_f = float(gate_critical)
    except Exception as exc:
        raise ValueError("Invalid phase2_gate_critical_slot_coverage_min") from exc
    if gate_critical_f < 0.0 or gate_critical_f > 1.0:
        raise ValueError("Invalid phase2_gate_critical_slot_coverage_min")
    gate_step_coverage_bypass = rules.get("phase2_gate_step_coverage_bypass_excellent", False)
    if not isinstance(gate_step_coverage_bypass, bool):
        raise ValueError("phase2_gate_step_coverage_bypass_excellent must be boolean")
    gate_logic_steps_coverage_min = rules.get("phase2_gate_logic_steps_coverage_min", 0.83)
    try:
        gate_logic_steps_coverage_min_f = float(gate_logic_steps_coverage_min)
    except Exception as exc:
        raise ValueError("Invalid phase2_gate_logic_steps_coverage_min") from exc
    if gate_logic_steps_coverage_min_f < 0.0 or gate_logic_steps_coverage_min_f > 1.0:
        raise ValueError("Invalid phase2_gate_logic_steps_coverage_min")
    gate_logic_steps_guard_validated = rules.get("phase2_gate_logic_steps_guard_validated", True)
    if not isinstance(gate_logic_steps_guard_validated, bool):
        raise ValueError("phase2_gate_logic_steps_guard_validated must be boolean")

    gate_step_bypass_min_critical_steps = int(
        rules.get("phase2_gate_step_bypass_min_critical_steps_with_claims", 2)
    )
    if gate_step_bypass_min_critical_steps < 1 or gate_step_bypass_min_critical_steps > 10:
        raise ValueError("Invalid phase2_gate_step_bypass_min_critical_steps_with_claims")
    gate_step_bypass_require_non_method_claim = rules.get("phase2_gate_step_bypass_require_non_method_claim", True)
    if not isinstance(gate_step_bypass_require_non_method_claim, bool):
        raise ValueError("phase2_gate_step_bypass_require_non_method_claim must be boolean")

    gate_critical_slot_bypass_min_coverage = rules.get("phase2_gate_critical_slot_bypass_min_coverage", 0.35)
    try:
        gate_critical_slot_bypass_min_coverage_f = float(gate_critical_slot_bypass_min_coverage)
    except Exception as exc:
        raise ValueError("Invalid phase2_gate_critical_slot_bypass_min_coverage") from exc
    if gate_critical_slot_bypass_min_coverage_f < 0.0 or gate_critical_slot_bypass_min_coverage_f > 1.0:
        raise ValueError("Invalid phase2_gate_critical_slot_bypass_min_coverage")

    gate_critical_slot_bypass_min_critical_steps = int(
        rules.get("phase2_gate_critical_slot_bypass_min_critical_steps_with_claims", 2)
    )
    if (
        gate_critical_slot_bypass_min_critical_steps < 1
        or gate_critical_slot_bypass_min_critical_steps > 10
    ):
        raise ValueError("Invalid phase2_gate_critical_slot_bypass_min_critical_steps_with_claims")
    gate_critical_slot_bypass_require_result_or_conclusion = rules.get(
        "phase2_gate_critical_slot_bypass_require_result_or_conclusion", True
    )
    if not isinstance(gate_critical_slot_bypass_require_result_or_conclusion, bool):
        raise ValueError("phase2_gate_critical_slot_bypass_require_result_or_conclusion must be boolean")

    gate_critical_slot_bypass_min_result_like_claims = int(
        rules.get("phase2_gate_critical_slot_bypass_min_result_like_claims", 1)
    )
    if gate_critical_slot_bypass_min_result_like_claims < 0 or gate_critical_slot_bypass_min_result_like_claims > 200:
        raise ValueError("Invalid phase2_gate_critical_slot_bypass_min_result_like_claims")
    gate_critical_slot_bypass_min_result_like_ratio = float(
        rules.get("phase2_gate_critical_slot_bypass_min_result_like_ratio", 0.0)
    )
    if gate_critical_slot_bypass_min_result_like_ratio < 0.0 or gate_critical_slot_bypass_min_result_like_ratio > 1.0:
        raise ValueError("Invalid phase2_gate_critical_slot_bypass_min_result_like_ratio")

    gate_base_min_non_method_critical_claims = int(
        rules.get("phase2_gate_base_min_non_method_critical_claims", 0)
    )
    if gate_base_min_non_method_critical_claims < 0 or gate_base_min_non_method_critical_claims > 200:
        raise ValueError("Invalid phase2_gate_base_min_non_method_critical_claims")
    gate_base_min_result_like_claims = int(
        rules.get("phase2_gate_base_min_result_like_claims", 0)
    )
    if gate_base_min_result_like_claims < 0 or gate_base_min_result_like_claims > 200:
        raise ValueError("Invalid phase2_gate_base_min_result_like_claims")
    gate_base_min_result_like_ratio = float(rules.get("phase2_gate_base_min_result_like_ratio", 0.0))
    if gate_base_min_result_like_ratio < 0.0 or gate_base_min_result_like_ratio > 1.0:
        raise ValueError("Invalid phase2_gate_base_min_result_like_ratio")

    gate_conflict = rules.get("phase2_gate_conflict_rate_max", 0.35)
    try:
        gate_conflict_f = float(gate_conflict)
    except Exception as exc:
        raise ValueError("Invalid phase2_gate_conflict_rate_max") from exc
    if gate_conflict_f < 0.0 or gate_conflict_f > 1.0:
        raise ValueError("Invalid phase2_gate_conflict_rate_max")
    conflict_mode = str(rules.get("phase2_conflict_mode", "lexical") or "").strip().lower()
    if conflict_mode not in {"lexical", "hybrid", "llm"}:
        raise ValueError("Invalid phase2_conflict_mode")
    conflict_semantic_threshold = float(rules.get("phase2_conflict_semantic_threshold", 0.75))
    if conflict_semantic_threshold < 0.0 or conflict_semantic_threshold > 1.0:
        raise ValueError("Invalid phase2_conflict_semantic_threshold")
    conflict_candidate_max_pairs = int(rules.get("phase2_conflict_candidate_max_pairs", 120))
    if conflict_candidate_max_pairs < 1 or conflict_candidate_max_pairs > 2000:
        raise ValueError("Invalid phase2_conflict_candidate_max_pairs")
    quality_tier_strategy = str(rules.get("phase2_quality_tier_strategy", "a1_fail_count") or "").strip().lower()
    if quality_tier_strategy not in {"a1_fail_count"}:
        raise ValueError("Invalid phase2_quality_tier_strategy")
    quality_tier_yellow_max = int(rules.get("phase2_quality_tier_yellow_max_failures", 1))
    if quality_tier_yellow_max < 0 or quality_tier_yellow_max > 10:
        raise ValueError("Invalid phase2_quality_tier_yellow_max_failures")
    quality_tier_red_min = int(rules.get("phase2_quality_tier_red_min_failures", 2))
    if quality_tier_red_min < 1 or quality_tier_red_min > 10:
        raise ValueError("Invalid phase2_quality_tier_red_min_failures")
    if quality_tier_red_min <= quality_tier_yellow_max:
        raise ValueError("phase2_quality_tier_red_min_failures must be > phase2_quality_tier_yellow_max_failures")
    conflict_shared_tokens = int(rules.get("phase2_conflict_shared_tokens_min") or 2)
    if conflict_shared_tokens < 1 or conflict_shared_tokens > 10:
        raise ValueError("Invalid phase2_conflict_shared_tokens_min")
    conflict_samples = int(rules.get("phase2_conflict_samples_max") or 8)
    if conflict_samples < 1 or conflict_samples > 100:
        raise ValueError("Invalid phase2_conflict_samples_max")
    conflict_gate_min_comparable_pairs = int(rules.get("phase2_conflict_gate_min_comparable_pairs", 3))
    if conflict_gate_min_comparable_pairs < 0 or conflict_gate_min_comparable_pairs > 200:
        raise ValueError("Invalid phase2_conflict_gate_min_comparable_pairs")
    conflict_gate_min_conflict_pairs = int(rules.get("phase2_conflict_gate_min_conflict_pairs", 1))
    if conflict_gate_min_conflict_pairs < 0 or conflict_gate_min_conflict_pairs > 200:
        raise ValueError("Invalid phase2_conflict_gate_min_conflict_pairs")
    for key in (
        "phase2_conflict_positive_terms_en",
        "phase2_conflict_negative_terms_en",
        "phase2_conflict_positive_terms_zh",
        "phase2_conflict_negative_terms_zh",
        "phase2_conflict_stop_terms_en",
        "phase2_conflict_stop_terms_zh",
    ):
        terms = rules.get(key)
        if terms is None:
            continue
        if not isinstance(terms, list):
            raise ValueError(f"{key} must be a list")
        if len(terms) > 200:
            raise ValueError(f"{key} is too long")
        for item in terms:
            s = str(item or "").strip()
            if not s:
                continue
            if len(s) > 64:
                raise ValueError(f"{key} contains too long term")
    citation_contexts = int(rules.get("citation_purpose_max_contexts_per_cite", 3))
    if citation_contexts < 1 or citation_contexts > 12:
        raise ValueError("Invalid citation_purpose_max_contexts_per_cite")
    citation_chars = int(rules.get("citation_purpose_max_context_chars", 900))
    if citation_chars < 120 or citation_chars > 8000:
        raise ValueError("Invalid citation_purpose_max_context_chars")
    citation_batch_max = int(rules.get("citation_purpose_max_cites_per_batch", 60))
    if citation_batch_max < 1 or citation_batch_max > 200:
        raise ValueError("Invalid citation_purpose_max_cites_per_batch")
    citation_labels_max = int(rules.get("citation_purpose_max_labels_per_cite", 3))
    if citation_labels_max < 1 or citation_labels_max > 8:
        raise ValueError("Invalid citation_purpose_max_labels_per_cite")
    citation_fallback_score = float(rules.get("citation_purpose_fallback_score", 0.4))
    if citation_fallback_score < 0.0 or citation_fallback_score > 1.0:
        raise ValueError("Invalid citation_purpose_fallback_score")
    reference_recovery_enabled = rules.get("reference_recovery_enabled", True)
    if not isinstance(reference_recovery_enabled, bool):
        raise ValueError("Invalid reference_recovery_enabled")
    reference_recovery_trigger_max_existing_refs = int(rules.get("reference_recovery_trigger_max_existing_refs", 0))
    if reference_recovery_trigger_max_existing_refs < 0 or reference_recovery_trigger_max_existing_refs > 200:
        raise ValueError("Invalid reference_recovery_trigger_max_existing_refs")
    reference_recovery_trigger_min_refs = int(rules.get("reference_recovery_trigger_min_refs", 0))
    if reference_recovery_trigger_min_refs < 0 or reference_recovery_trigger_min_refs > 500:
        raise ValueError("Invalid reference_recovery_trigger_min_refs")
    reference_recovery_trigger_min_refs_per_1k_chars = float(rules.get("reference_recovery_trigger_min_refs_per_1k_chars", 0.0))
    if reference_recovery_trigger_min_refs_per_1k_chars < 0.0 or reference_recovery_trigger_min_refs_per_1k_chars > 10.0:
        raise ValueError("Invalid reference_recovery_trigger_min_refs_per_1k_chars")
    reference_recovery_max_refs = int(rules.get("reference_recovery_max_refs", 180))
    if reference_recovery_max_refs < 1 or reference_recovery_max_refs > 500:
        raise ValueError("Invalid reference_recovery_max_refs")
    reference_recovery_doc_chars_max = int(rules.get("reference_recovery_doc_chars_max", 48000))
    if reference_recovery_doc_chars_max < 1000 or reference_recovery_doc_chars_max > 200000:
        raise ValueError("Invalid reference_recovery_doc_chars_max")
    reference_recovery_agent_timeout_sec = float(rules.get("reference_recovery_agent_timeout_sec", 45.0))
    if reference_recovery_agent_timeout_sec < 0.5 or reference_recovery_agent_timeout_sec > 300.0:
        raise ValueError("Invalid reference_recovery_agent_timeout_sec")
    citation_event_recovery_enabled = rules.get("citation_event_recovery_enabled", True)
    if not isinstance(citation_event_recovery_enabled, bool):
        raise ValueError("Invalid citation_event_recovery_enabled")
    citation_event_recovery_trigger = int(rules.get("citation_event_recovery_trigger_max_existing_events", 0))
    if citation_event_recovery_trigger < 0 or citation_event_recovery_trigger > 50:
        raise ValueError("Invalid citation_event_recovery_trigger_max_existing_events")
    for key in (
        "citation_event_recovery_numeric_bracket_enabled",
        "citation_event_recovery_paren_numeric_enabled",
        "citation_event_recovery_author_year_enabled",
    ):
        raw = rules.get(key, True if key != "citation_event_recovery_paren_numeric_enabled" else False)
        if not isinstance(raw, bool):
            raise ValueError(f"Invalid {key}")
    citation_event_recovery_max_events_per_chunk = int(rules.get("citation_event_recovery_max_events_per_chunk", 6))
    if citation_event_recovery_max_events_per_chunk < 1 or citation_event_recovery_max_events_per_chunk > 40:
        raise ValueError("Invalid citation_event_recovery_max_events_per_chunk")
    citation_event_recovery_context_chars = int(rules.get("citation_event_recovery_context_chars", 800))
    if citation_event_recovery_context_chars < 120 or citation_event_recovery_context_chars > 4000:
        raise ValueError("Invalid citation_event_recovery_context_chars")
    for key in (
        "phase1_noise_filter_enabled",
        "phase1_noise_filter_figure_caption_enabled",
        "phase1_noise_filter_pure_definition_enabled",
    ):
        raw = rules.get(key, True)
        if not isinstance(raw, bool):
            raise ValueError(f"Invalid {key}")
    crossref_confidence_threshold = float(rules.get("crossref_confidence_threshold", 0.55))
    if crossref_confidence_threshold < 0.0 or crossref_confidence_threshold > 1.0:
        raise ValueError("Invalid crossref_confidence_threshold")
    et = str(rules.get("evidence_verification") or "llm")
    if et not in {"llm", "off"}:
        raise ValueError("rules.evidence_verification must be 'llm' or 'off'")

    req_kinds = rules.get("require_targets_for_kinds") or []
    if not isinstance(req_kinds, list):
        raise ValueError("rules.require_targets_for_kinds must be a list")
    for x in req_kinds:
        if str(x) not in kind_ids:
            # allow referencing disabled kinds but it still must exist
            raise ValueError(f"rules.require_targets_for_kinds contains unknown kind id: {x!r}")

    prompts = schema.get("prompts")
    if prompts is not None:
        if not isinstance(prompts, dict):
            raise ValueError("prompts must be an object")
        for k, v in prompts.items():
            kk = str(k or "")
            if not _PROMPT_KEY_RE.match(kk):
                raise ValueError(f"Invalid prompt key: {kk!r}")
            if not isinstance(v, str):
                raise ValueError(f"prompts[{kk!r}] must be a string")
            if len(v) > 20000:
                raise ValueError(f"prompts[{kk!r}] is too long (max 20000 chars)")


def ensure_defaults() -> None:
    for pt in PAPER_TYPES:
        paper_type: PaperType = pt  # type: ignore[assignment]
        d = _paper_type_dir(paper_type)
        if not _active_path(paper_type).exists():
            s = _default_schema(paper_type)
            _write_json(_version_path(paper_type, 1), s)
            _write_json(_active_path(paper_type), {"active_version": 1})
        else:
            # Ensure the active version file exists (avoid recursion into load_active()).
            try:
                active = _read_json(_active_path(paper_type))
                v = int(active.get("active_version") or 1)
                _ = load_version(paper_type, v).get("version")
            except Exception:
                s = _default_schema(paper_type)
                _write_json(_version_path(paper_type, 1), s)
                _write_json(_active_path(paper_type), {"active_version": 1})


def list_versions(paper_type: PaperType) -> list[SchemaVersionInfo]:
    d = _paper_type_dir(paper_type)
    out: list[SchemaVersionInfo] = []
    for p in sorted(d.glob("v*.json")):
        m = re.match(r"^v(\d+)\.json$", p.name)
        if not m:
            continue
        label = ""
        try:
            obj = _read_json(p)
            label = str(obj.get("name") or "").strip()
        except Exception:
            label = ""
        out.append(SchemaVersionInfo(paper_type=paper_type, version=int(m.group(1)), path=p, name=label))
    out.sort(key=lambda x: x.version, reverse=True)
    return out


def load_version(paper_type: PaperType, version: int) -> dict[str, Any]:
    p = _version_path(paper_type, version)
    if not p.exists():
        raise FileNotFoundError(f"Schema version not found: {paper_type} v{version}")
    s = _read_json(p)
    validate_schema(s)
    s["paper_type"] = paper_type
    s["version"] = int(version)
    return s


def load_active(paper_type: PaperType) -> dict[str, Any]:
    ensure_defaults()
    ap = _active_path(paper_type)
    active = _read_json(ap)
    v = int(active.get("active_version") or 1)
    return load_version(paper_type, v)


def activate_version(paper_type: PaperType, version: int) -> dict[str, Any]:
    s = load_version(paper_type, version)
    _write_json(_active_path(paper_type), {"active_version": int(version)})
    return s


def delete_version(paper_type: PaperType, version: int) -> dict[str, Any]:
    ensure_defaults()
    v = int(version)
    p = _version_path(paper_type, v)
    if not p.exists():
        raise FileNotFoundError(f"Schema version not found: {paper_type} v{v}")

    versions = list_versions(paper_type)
    if len(versions) <= 1:
        raise ValueError("Cannot delete the last schema version")

    active_meta = _read_json(_active_path(paper_type))
    old_active = int(active_meta.get("active_version") or 1)

    p.unlink(missing_ok=False)

    remaining = list_versions(paper_type)
    if not remaining:
        # Safety net: should not happen due to len check above.
        s = _default_schema(paper_type)
        _write_json(_version_path(paper_type, 1), s)
        _write_json(_active_path(paper_type), {"active_version": 1})
        return {
            "paper_type": paper_type,
            "deleted_version": v,
            "active_version": 1,
            "active_changed": True,
        }

    if old_active == v or not _version_path(paper_type, old_active).exists():
        new_active = int(remaining[0].version)
        _write_json(_active_path(paper_type), {"active_version": new_active})
        active_changed = True
    else:
        new_active = old_active
        active_changed = False

    return {
        "paper_type": paper_type,
        "deleted_version": v,
        "active_version": int(new_active),
        "active_changed": bool(active_changed),
    }


def create_new_version(paper_type: PaperType, schema: dict[str, Any], activate: bool = True) -> dict[str, Any]:
    ensure_defaults()
    versions = list_versions(paper_type)
    next_v = (versions[0].version + 1) if versions else 1
    schema = dict(schema)
    schema["paper_type"] = paper_type
    schema["version"] = int(next_v)
    validate_schema(schema)
    _write_json(_version_path(paper_type, next_v), schema)
    if activate:
        _write_json(_active_path(paper_type), {"active_version": int(next_v)})
    return schema
