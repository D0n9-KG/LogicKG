from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.ops_config_store import (
    load_profile,
    merge_discovery_config,
    merge_similarity_config,
    normalize_discovery_config,
    normalize_profile,
    normalize_similarity_config,
    save_profile,
)
from app.schema_store import load_active
from app.settings import settings


router = APIRouter(prefix="/config-center", tags=["config-center"])


DISCOVERY_FIELD_HELP: dict[str, str] = {
    "domain": "Research topic/domain keyword used to filter gap seeds.",
    "max_gaps": "Maximum gap seeds processed in one discovery batch.",
    "candidates_per_gap": "Question candidates generated for each gap.",
    "hop_order": "Author-hop graph expansion depth.",
    "adjacent_samples": "Samples pulled from adjacent (local neighborhood) papers.",
    "random_samples": "Random exploration samples to reduce local bias.",
    "rag_top_k": "Local evidence chunks injected into generation per candidate.",
    "community_method": "Community sampling strategy: author_hop / louvain / hybrid.",
    "community_samples": "Extra papers sampled from the community strategy.",
    "prompt_optimization_method": "Prompt optimizer policy: rl_bandit / heuristic.",
    "dry_run": "If true, run pipeline without writing resulting artifacts.",
    "use_llm": "If true, enable LLM-based question generation.",
    "prompt_optimize": "If true, enable prompt variant optimization loop.",
}

SIMILARITY_FIELD_HELP: dict[str, str] = {
    "group_clustering_method": "Grouping method for similarity clusters.",
    "group_clustering_threshold": "Similarity threshold used when forming retrieval clusters.",
}


class ConfigCenterProfileUpdateRequest(BaseModel):
    modules: dict[str, Any] = Field(default_factory=dict)


class ConfigAssistantRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=2000)
    max_suggestions: int = Field(default=8, ge=1, le=20)
    locale: str | None = Field(default=None, description="UI locale hint (zh-CN / en-US).")


class ConfigAssistantSuggestion(BaseModel):
    module: str
    key: str
    anchor: str
    suggested_value: str
    rationale: str
    focus_key: str | None = None
    caution: str | None = None


class _LLMSuggestion(BaseModel):
    module: str
    key: str
    anchor: str
    suggested_value: str
    rationale: str
    focus_key: str | None = None
    caution: str | None = None


class _LLMSuggestionResponse(BaseModel):
    suggestions: list[_LLMSuggestion]


def _normalize_locale(locale: str | None) -> str:
    text = str(locale or "").strip().lower()
    if text == "zh" or text.startswith("zh-"):
        return "zh-CN"
    return "en-US"


def _schema_key_catalog() -> tuple[list[str], list[str]]:
    try:
        schema = load_active("research")
    except Exception:
        return [], []
    rules = schema.get("rules") if isinstance(schema.get("rules"), dict) else {}
    prompts = schema.get("prompts") if isinstance(schema.get("prompts"), dict) else {}
    rule_keys = sorted(str(k) for k in rules.keys() if str(k).strip())
    prompt_keys = sorted(str(k) for k in prompts.keys() if str(k).strip())
    return rule_keys, prompt_keys


def _catalog(profile: dict[str, Any]) -> dict[str, Any]:
    modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
    discovery = modules.get("discovery") if isinstance(modules.get("discovery"), dict) else {}
    similarity = modules.get("similarity") if isinstance(modules.get("similarity"), dict) else {}
    rule_keys, prompt_keys = _schema_key_catalog()

    return {
        "modules": [
            {
                "id": "discovery",
                "label": "Discovery Batch",
                "fields": [
                    {
                        "key": key,
                        "anchor": f"discovery.{key}",
                        "description": desc,
                        "current_value": discovery.get(key),
                    }
                    for key, desc in DISCOVERY_FIELD_HELP.items()
                ],
            },
            {
                "id": "similarity",
                "label": "Similarity & Clustering",
                "fields": [
                    {
                        "key": key,
                        "anchor": f"similarity.{key}",
                        "description": desc,
                        "current_value": similarity.get(key),
                    }
                    for key, desc in SIMILARITY_FIELD_HELP.items()
                ],
            },
            {
                "id": "schema",
                "label": "Extraction Policy (Schema + Prompts)",
                "fields": [
                    {
                        "key": "rules_json",
                        "anchor": "schema.rules_json",
                        "description": "Edit full extraction rules JSON. Use focus_key to locate a specific rule.",
                    },
                    {
                        "key": "prompts_json",
                        "anchor": "schema.prompts_json",
                        "description": "Edit full prompt overrides JSON. Use focus_key to locate a specific prompt.",
                    },
                ],
                "rule_keys": rule_keys,
                "prompt_keys": prompt_keys,
            },
        ]
    }


def _add_suggestion(
    out: list[dict[str, Any]],
    *,
    module: str,
    key: str,
    anchor: str,
    suggested_value: Any,
    rationale: str,
    focus_key: str | None = None,
    caution: str | None = None,
) -> None:
    signature = f"{module}:{anchor}:{focus_key or ''}"
    if any((x.get("_sig") == signature) for x in out):
        return
    out.append(
        {
            "_sig": signature,
            "module": module,
            "key": key,
            "anchor": anchor,
            "suggested_value": str(suggested_value),
            "rationale": rationale,
            "focus_key": focus_key,
            "caution": caution,
        }
    )


def _normalized_goal_text(goal: str) -> str:
    return " ".join(str(goal or "").strip().lower().split())


def _goal_mentions_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _preferred_assistant_modules(goal: str) -> set[str] | None:
    text = _normalized_goal_text(goal)
    if not text:
        return None

    extraction_tokens = (
        "extract",
        "extraction",
        "knowledge graph",
        "graph extraction",
        "schema",
        "claim",
        "claims",
        "evidence",
        "citation",
        "prompt",
        "unsupported",
        "hallucination",
        "\u62bd\u53d6",
        "\u77e5\u8bc6\u56fe\u8c31",
        "\u56fe\u8c31",
        "\u8bba\u65ad",
        "\u8bc1\u636e",
        "\u5f15\u6587",
        "\u63d0\u793a\u8bcd",
    )
    discovery_tokens = (
        "discovery",
        "gap",
        "gap seed",
        "candidate question",
        "question mining",
        "\u79d1\u5b66\u53d1\u73b0",
        "\u95ee\u9898\u53d1\u73b0",
        "\u95ee\u9898\u6316\u6398",
        "\u5019\u9009\u95ee\u9898",
    )

    if _goal_mentions_any(text, extraction_tokens) and not _goal_mentions_any(text, discovery_tokens):
        return {"schema", "similarity"}
    return None


def _heuristic_suggestions(
    goal: str,
    profile: dict[str, Any],
    max_items: int,
    *,
    locale: str = "en-US",
) -> list[dict[str, Any]]:
    normalized_locale = _normalize_locale(locale)
    preferred_modules = _preferred_assistant_modules(goal)
    allow_discovery = preferred_modules is None or "discovery" in preferred_modules

    def text_by_locale(zh: str, en: str) -> str:
        return zh if normalized_locale == "zh-CN" else en

    text = (goal or "").strip().lower()
    modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
    discovery = normalize_discovery_config(modules.get("discovery") if isinstance(modules.get("discovery"), dict) else {})
    similarity = normalize_similarity_config(modules.get("similarity") if isinstance(modules.get("similarity"), dict) else {})
    out: list[dict[str, Any]] = []

    precision_tokens = ["精准", "精确", "precision", "strict", "噪声", "noise", "hallucination", "可靠", "可信"]
    recall_tokens = ["召回", "覆盖", "coverage", "更多", "broader", "explore", "diversity", "发散"]
    speed_tokens = ["快", "速度", "耗时", "latency", "faster", "成本", "cost", "cheap"]

    wants_precision = any(t in text for t in precision_tokens)
    wants_recall = any(t in text for t in recall_tokens)
    wants_speed = any(t in text for t in speed_tokens)

    if wants_precision:
        _add_suggestion(
            out,
            module="discovery",
            key="max_gaps",
            anchor="discovery.max_gaps",
            suggested_value=max(4, min(12, int(discovery["max_gaps"]) - 2)),
            rationale=text_by_locale("收窄批处理范围，优先聚焦高置信度的 gap seed。", "Reduce batch spread to focus on higher-confidence gap seeds."),
            caution=text_by_locale("设得过低可能漏掉长尾机会。", "Too low may miss long-tail opportunities."),
        )
        _add_suggestion(
            out,
            module="discovery",
            key="rag_top_k",
            anchor="discovery.rag_top_k",
            suggested_value=max(2, min(6, int(discovery["rag_top_k"]) - 1)),
            rationale=text_by_locale("减小局部证据数量，减少噪声上下文注入。", "Smaller local evidence set reduces noisy context injection."),
        )
        _add_suggestion(
            out,
            module="similarity",
            key="group_clustering_threshold",
            anchor="similarity.group_clustering_threshold",
            suggested_value=f"{min(0.95, float(similarity['group_clustering_threshold']) + 0.03):.2f}",
            rationale=text_by_locale("提高聚类阈值可让相似性簇更紧，降低语义漂移。", "Higher threshold creates tighter similarity clusters, reducing semantic drift."),
        )
        _add_suggestion(
            out,
            module="schema",
            key="rules_json",
            anchor="schema.rules_json",
            suggested_value="0.60",
            rationale=text_by_locale("提高 grounded claim 的通过下限，增强抽取精度。", "Raise grounded-claim acceptance floor for stronger extraction precision."),
            focus_key="phase1_gate_supported_ratio_min",
        )
        _add_suggestion(
            out,
            module="schema",
            key="prompts_json",
            anchor="schema.prompts_json",
            suggested_value=text_by_locale("强化抗幻觉与仅基于引用证据作答的约束。", "Strengthen anti-hallucination and citation-only constraints."),
            rationale=text_by_locale("收紧抽取提示词约束，减少无证据支撑的主张。", "Tighten extraction prompt constraints to avoid unsupported claims."),
            focus_key="phase1_chunk_claim_extract_system",
        )

    if wants_recall:
        _add_suggestion(
            out,
            module="discovery",
            key="max_gaps",
            anchor="discovery.max_gaps",
            suggested_value=min(24, int(discovery["max_gaps"]) + 4),
            rationale=text_by_locale("增加探索的 gap seed 数量，扩大候选覆盖面。", "Increase explored gap seeds to widen candidate coverage."),
            caution=text_by_locale("可能增加人工审阅负担。", "May increase review load."),
        )
        _add_suggestion(
            out,
            module="discovery",
            key="random_samples",
            anchor="discovery.random_samples",
            suggested_value=min(10, int(discovery["random_samples"]) + 2),
            rationale=text_by_locale("提高随机探索采样，降低局部图偏置。", "Boost random exploration to reduce local graph bias."),
        )
        _add_suggestion(
            out,
            module="discovery",
            key="community_method",
            anchor="discovery.community_method",
            suggested_value="hybrid",
            rationale=text_by_locale(
                "hybrid 采样可以兼顾 author-hop 的局部性与社区多样性。",
                "Hybrid sampling mixes author-hop locality with community diversity.",
            ),
        )
        _add_suggestion(
            out,
            module="schema",
            key="rules_json",
            anchor="schema.rules_json",
            suggested_value="0.45",
            rationale=text_by_locale(
                "适当降低初始 supported ratio 阈值，为下游筛选保留更多候选主张。",
                "Lower initial supported ratio threshold to keep more candidate claims for downstream filtering.",
            ),
            focus_key="phase1_gate_supported_ratio_min",
            caution=text_by_locale("需要更强的后审计来控制额外噪声。", "Requires stronger post-audit to avoid extra noise."),
        )

    if wants_speed:
        _add_suggestion(
            out,
            module="discovery",
            key="max_gaps",
            anchor="discovery.max_gaps",
            suggested_value=max(3, int(discovery["max_gaps"]) - 3),
            rationale=text_by_locale("减少 gap seed 数量可直接降低生成与审计调用总量。", "Fewer gap seeds reduce total generation and audit calls."),
        )
        _add_suggestion(
            out,
            module="discovery",
            key="adjacent_samples",
            anchor="discovery.adjacent_samples",
            suggested_value=max(2, int(discovery["adjacent_samples"]) - 2),
            rationale=text_by_locale("缩小邻域采样规模，降低上下文构建成本。", "Smaller neighborhood sampling lowers context-building cost."),
        )
        _add_suggestion(
            out,
            module="discovery",
            key="prompt_optimize",
            anchor="discovery.prompt_optimize",
            suggested_value="false",
            rationale=text_by_locale(
                "关闭 prompt 优化循环可以减少额外迭代，缩短整体耗时。",
                "Disabling prompt optimization removes extra generation loops and shortens runtime.",
            ),
        )

    if not out:
        _add_suggestion(
            out,
            module="discovery",
            key="max_gaps",
            anchor="discovery.max_gaps",
            suggested_value=discovery["max_gaps"],
            rationale=text_by_locale(
                "先保持 max_gaps 不变；每轮只调一个变量，更便于做清晰 A/B 对比。",
                "Keep max_gaps stable first; tune one variable per iteration for clearer A/B comparison.",
            ),
        )
        _add_suggestion(
            out,
            module="discovery",
            key="rag_top_k",
            anchor="discovery.rag_top_k",
            suggested_value=discovery["rag_top_k"],
            rationale=text_by_locale("通过 rag_top_k 在上下文丰富度与精度/噪声之间做权衡。", "Use rag_top_k to trade off context richness vs. precision/noise."),
        )
        _add_suggestion(
            out,
            module="similarity",
            key="group_clustering_threshold",
            anchor="similarity.group_clustering_threshold",
            suggested_value=f"{float(similarity['group_clustering_threshold']):.2f}",
            rationale=text_by_locale(
                "聚类阈值会直接影响相似性簇粒度以及下游 gap 质量。",
                "Cluster threshold strongly affects similarity-cluster granularity and downstream gap quality.",
            ),
        )
        _add_suggestion(
            out,
            module="schema",
            key="rules_json",
            anchor="schema.rules_json",
            suggested_value=text_by_locale("建议复核", "Review"),
            rationale=text_by_locale("结合当前目标校准抽取门限与冲突阈值。", "Calibrate extraction gates and conflict thresholds for your objective."),
            focus_key="phase1_gate_supported_ratio_min",
        )
        _add_suggestion(
            out,
            module="schema",
            key="prompts_json",
            anchor="schema.prompts_json",
            suggested_value=text_by_locale("建议复核", "Review"),
            rationale=text_by_locale(
                "当偏差主要来自语义/表达风格时，优先调提示词约束。",
                "Tune prompt constraints when behavior mismatch is mainly semantic/style-driven.",
            ),
            focus_key="logic_claims_system",
        )

    cleaned = [{k: v for k, v in row.items() if k != "_sig"} for row in out]
    return cleaned[:max_items]


def _llm_suggestions(
    goal: str,
    profile: dict[str, Any],
    catalog: dict[str, Any],
    max_items: int,
    *,
    locale: str = "en-US",
) -> list[dict[str, Any]] | None:
    normalized_locale = _normalize_locale(locale)
    if not settings.effective_llm_api_key():
        return None
    try:
        from app.llm.client import call_validated_json
    except Exception:
        return None

    allowed_anchors: list[str] = []
    for module in (catalog.get("modules") or []):
        if not isinstance(module, dict):
            continue
        for field in (module.get("fields") or []):
            if isinstance(field, dict) and str(field.get("anchor") or "").strip():
                allowed_anchors.append(str(field.get("anchor")))

    if normalized_locale == "zh-CN":
        system = (
            "你是 LogicKG 运维配置助手。只输出严格 JSON，不要输出 Markdown 或额外解释。\n"
            "根据用户目标给出可执行的配置调优建议。\n"
            "每条建议的 anchor 必须来自 allowed anchors。\n"
            "rationale 与 caution 必须使用简体中文（配置 key/anchor 保持原样）。\n"
            "建议应简洁、具体、可落地。\n"
        )
        user = (
            f"目标:\n{goal}\n\n"
            f"最多建议条数: {max_items}\n\n"
            f"Allowed anchors:\n{allowed_anchors}\n\n"
            f"当前配置 Profile JSON:\n{profile}\n\n"
            "输出 JSON 结构:\n"
            "{\n"
            "  \"suggestions\": [\n"
            "    {\n"
            "      \"module\": \"discovery|similarity|schema\",\n"
            "      \"key\": \"参数名\",\n"
            "      \"anchor\": \"allowed anchors 之一\",\n"
            "      \"suggested_value\": \"建议值或简短变更说明\",\n"
            "      \"rationale\": \"为何有帮助（中文）\",\n"
            "      \"focus_key\": \"可选 schema key\",\n"
            "      \"caution\": \"可选风险提示（中文）\"\n"
            "    }\n"
            "  ]\n"
            "}"
        )
    else:
        system = (
            "You are LogicKG Config Assistant. Return STRICT JSON only.\n"
            "Produce operational tuning suggestions for the user's optimization goal.\n"
            "Each suggestion MUST use an anchor from the allowed anchors list.\n"
            "Keep suggestions concrete, short, and actionable.\n"
        )
        user = (
            f"Goal:\n{goal}\n\n"
            f"Max suggestions: {max_items}\n\n"
            f"Allowed anchors:\n{allowed_anchors}\n\n"
            f"Current profile JSON:\n{profile}\n\n"
            "Output JSON schema:\n"
            "{\n"
            "  \"suggestions\": [\n"
            "    {\n"
            "      \"module\": \"discovery|similarity|schema\",\n"
            "      \"key\": \"parameter_name\",\n"
            "      \"anchor\": \"one_of_allowed_anchors\",\n"
            "      \"suggested_value\": \"new value or concise change\",\n"
            "      \"rationale\": \"why this helps\",\n"
            "      \"focus_key\": \"optional schema key\",\n"
            "      \"caution\": \"optional risk\"\n"
            "    }\n"
            "  ]\n"
            "}"
        )
    try:
        parsed = call_validated_json(system=system, user=user, model_class=_LLMSuggestionResponse, max_retries=1)
    except Exception:
        return None

    normalized: list[dict[str, Any]] = []
    anchor_set = set(allowed_anchors)
    for item in parsed.suggestions:
        if item.anchor not in anchor_set:
            continue
        normalized.append(item.model_dump())
    if not normalized:
        return None
    return normalized[:max_items]


def _heuristic_suggestions(
    goal: str,
    profile: dict[str, Any],
    max_items: int,
    *,
    locale: str = "en-US",
) -> list[dict[str, Any]]:
    normalized_locale = _normalize_locale(locale)
    preferred_modules = _preferred_assistant_modules(goal)
    allow_discovery = preferred_modules is None or "discovery" in preferred_modules

    def text_by_locale(zh: str, en: str) -> str:
        return zh if normalized_locale == "zh-CN" else en

    text = _normalized_goal_text(goal)
    modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
    discovery = normalize_discovery_config(modules.get("discovery") if isinstance(modules.get("discovery"), dict) else {})
    similarity = normalize_similarity_config(modules.get("similarity") if isinstance(modules.get("similarity"), dict) else {})
    out: list[dict[str, Any]] = []

    precision_tokens = (
        "precision",
        "strict",
        "noise",
        "hallucination",
        "reliable",
        "\u51c6\u786e",
        "\u7cbe\u51c6",
        "\u7cbe\u786e",
        "\u566a\u58f0",
        "\u53ef\u9760",
        "\u53ef\u4fe1",
    )
    recall_tokens = (
        "coverage",
        "broader",
        "explore",
        "diversity",
        "\u53ec\u56de",
        "\u8986\u76d6",
        "\u66f4\u591a",
        "\u53d1\u6563",
    )
    speed_tokens = (
        "latency",
        "faster",
        "cost",
        "cheap",
        "\u901f\u5ea6",
        "\u8017\u65f6",
        "\u6210\u672c",
        "\u66f4\u5feb",
        "\u66f4\u7701",
    )

    wants_precision = _goal_mentions_any(text, precision_tokens)
    wants_recall = _goal_mentions_any(text, recall_tokens)
    wants_speed = _goal_mentions_any(text, speed_tokens)

    if wants_precision:
        if allow_discovery:
            _add_suggestion(
                out,
                module="discovery",
                key="max_gaps",
                anchor="discovery.max_gaps",
                suggested_value=max(4, min(12, int(discovery["max_gaps"]) - 2)),
                rationale=text_by_locale("收窄发现批次范围，优先保留高置信度 gap seed。", "Reduce batch spread to focus on higher-confidence gap seeds."),
                caution=text_by_locale("设置过低可能会漏掉长尾机会。", "Too low may miss long-tail opportunities."),
            )
            _add_suggestion(
                out,
                module="discovery",
                key="rag_top_k",
                anchor="discovery.rag_top_k",
                suggested_value=max(2, min(6, int(discovery["rag_top_k"]) - 1)),
                rationale=text_by_locale("减少候选生成时注入的局部证据，降低噪声上下文。", "Smaller local evidence set reduces noisy context injection."),
            )
        _add_suggestion(
            out,
            module="similarity",
            key="group_clustering_threshold",
            anchor="similarity.group_clustering_threshold",
            suggested_value=f"{min(0.95, float(similarity['group_clustering_threshold']) + 0.03):.2f}",
            rationale=text_by_locale("提高聚类阈值，让相似性簇更紧，减少语义漂移。", "Higher threshold creates tighter similarity clusters, reducing semantic drift."),
        )
        _add_suggestion(
            out,
            module="schema",
            key="rules_json",
            anchor="schema.rules_json",
            suggested_value="0.60",
            rationale=text_by_locale("提高 grounded claim 的通过下限，增强抽取精度。", "Raise grounded-claim acceptance floor for stronger extraction precision."),
            focus_key="phase1_gate_supported_ratio_min",
        )
        _add_suggestion(
            out,
            module="schema",
            key="prompts_json",
            anchor="schema.prompts_json",
            suggested_value=text_by_locale("强化抗幻觉与仅基于证据生成主张的约束。", "Strengthen anti-hallucination and evidence-only extraction constraints."),
            rationale=text_by_locale("收紧抽取提示词约束，减少无证据支撑的主张。", "Tighten extraction prompt constraints to avoid unsupported claims."),
            focus_key="phase1_chunk_claim_extract_system",
        )

    if wants_recall:
        if allow_discovery:
            _add_suggestion(
                out,
                module="discovery",
                key="max_gaps",
                anchor="discovery.max_gaps",
                suggested_value=min(24, int(discovery["max_gaps"]) + 4),
                rationale=text_by_locale("增加 gap seed 数量，扩大候选覆盖面。", "Increase explored gap seeds to widen candidate coverage."),
                caution=text_by_locale("可能会增加人工审核负担。", "May increase review load."),
            )
            _add_suggestion(
                out,
                module="discovery",
                key="random_samples",
                anchor="discovery.random_samples",
                suggested_value=min(10, int(discovery["random_samples"]) + 2),
                rationale=text_by_locale("提升随机探索采样，降低局部图偏置。", "Boost random exploration to reduce local graph bias."),
            )
            _add_suggestion(
                out,
                module="discovery",
                key="community_method",
                anchor="discovery.community_method",
                suggested_value="hybrid",
                rationale=text_by_locale("混合社区采样兼顾 author-hop 局部性与社区多样性。", "Hybrid sampling mixes author-hop locality with community diversity."),
            )
        _add_suggestion(
            out,
            module="schema",
            key="rules_json",
            anchor="schema.rules_json",
            suggested_value="0.45",
            rationale=text_by_locale("适度降低 supported ratio 下限，为后续过滤保留更多候选主张。", "Lower initial supported ratio threshold to keep more candidate claims for downstream filtering."),
            focus_key="phase1_gate_supported_ratio_min",
            caution=text_by_locale("需要更强的后审计来控制新增噪声。", "Requires stronger post-audit to avoid extra noise."),
        )

    if wants_speed and allow_discovery:
        _add_suggestion(
            out,
            module="discovery",
            key="max_gaps",
            anchor="discovery.max_gaps",
            suggested_value=max(3, int(discovery["max_gaps"]) - 3),
            rationale=text_by_locale("减少 gap seed 数量可直接降低生成与审计调用量。", "Fewer gap seeds reduce total generation and audit calls."),
        )
        _add_suggestion(
            out,
            module="discovery",
            key="adjacent_samples",
            anchor="discovery.adjacent_samples",
            suggested_value=max(2, int(discovery["adjacent_samples"]) - 2),
            rationale=text_by_locale("缩小邻域采样规模，降低上下文构建成本。", "Smaller neighborhood sampling lowers context-building cost."),
        )
        _add_suggestion(
            out,
            module="discovery",
            key="prompt_optimize",
            anchor="discovery.prompt_optimize",
            suggested_value="false",
            rationale=text_by_locale("关闭提示词优化循环，减少额外迭代。", "Disabling prompt optimization removes extra generation loops and shortens runtime."),
        )

    if not out:
        if allow_discovery:
            _add_suggestion(
                out,
                module="discovery",
                key="max_gaps",
                anchor="discovery.max_gaps",
                suggested_value=discovery["max_gaps"],
                rationale=text_by_locale("先保持 max_gaps 不变，每次只调整一个变量，便于做清晰 A/B 对比。", "Keep max_gaps stable first; tune one variable per iteration for clearer A/B comparison."),
            )
            _add_suggestion(
                out,
                module="discovery",
                key="rag_top_k",
                anchor="discovery.rag_top_k",
                suggested_value=discovery["rag_top_k"],
                rationale=text_by_locale("通过 rag_top_k 平衡上下文丰富度与噪声。", "Use rag_top_k to trade off context richness vs. precision/noise."),
            )
        _add_suggestion(
            out,
            module="similarity",
            key="group_clustering_threshold",
            anchor="similarity.group_clustering_threshold",
            suggested_value=f"{float(similarity['group_clustering_threshold']):.2f}",
            rationale=text_by_locale("聚类阈值会直接影响相似性簇粒度以及下游质量。", "Cluster threshold strongly affects similarity-cluster granularity and downstream quality."),
        )
        _add_suggestion(
            out,
            module="schema",
            key="rules_json",
            anchor="schema.rules_json",
            suggested_value=text_by_locale("建议复核", "Review"),
            rationale=text_by_locale("结合当前目标校准抽取门限与冲突阈值。", "Calibrate extraction gates and conflict thresholds for your objective."),
            focus_key="phase1_gate_supported_ratio_min",
        )
        _add_suggestion(
            out,
            module="schema",
            key="prompts_json",
            anchor="schema.prompts_json",
            suggested_value=text_by_locale("建议复核", "Review"),
            rationale=text_by_locale("当偏差主要来自语义表达时，优先调整提示词约束。", "Tune prompt constraints when behavior mismatch is mainly semantic or style driven."),
            focus_key="logic_claims_system",
        )

    cleaned = [{k: v for k, v in row.items() if k != "_sig"} for row in out]
    return cleaned[:max_items]


def _llm_suggestions(
    goal: str,
    profile: dict[str, Any],
    catalog: dict[str, Any],
    max_items: int,
    *,
    locale: str = "en-US",
) -> list[dict[str, Any]] | None:
    normalized_locale = _normalize_locale(locale)
    if not settings.effective_llm_api_key():
        return None
    try:
        from app.llm.client import call_validated_json
    except Exception:
        return None

    preferred_modules = _preferred_assistant_modules(goal)
    allowed_anchors: list[str] = []
    for module in (catalog.get("modules") or []):
        if not isinstance(module, dict):
            continue
        module_id = str(module.get("id") or "").strip()
        if preferred_modules is not None and module_id and module_id not in preferred_modules:
            continue
        for field in (module.get("fields") or []):
            if isinstance(field, dict) and str(field.get("anchor") or "").strip():
                allowed_anchors.append(str(field.get("anchor")))

    if not allowed_anchors:
        return None

    if normalized_locale == "zh-CN":
        system = (
            "你是 LogicKG 运维配置助手。只输出严格 JSON，不要输出 Markdown 或额外解释。\n"
            "根据用户目标给出可执行的配置调优建议。\n"
            "每条建议的 anchor 必须来自 allowed anchors。\n"
            "rationale 与 caution 必须使用简体中文（配置 key/anchor 保持原样）。\n"
            "建议应简洁、具体、可落地。\n"
        )
        user = (
            f"目标:\n{goal}\n\n"
            f"最多建议条数: {max_items}\n\n"
            f"Allowed anchors:\n{allowed_anchors}\n\n"
            f"当前配置 Profile JSON:\n{profile}\n\n"
            "输出 JSON 结构:\n"
            "{\n"
            "  \"suggestions\": [\n"
            "    {\n"
            "      \"module\": \"discovery|similarity|schema\",\n"
            "      \"key\": \"参数名\",\n"
            "      \"anchor\": \"allowed anchors 之一\",\n"
            "      \"suggested_value\": \"建议值或简短变更说明\",\n"
            "      \"rationale\": \"为何有帮助（中文）\",\n"
            "      \"focus_key\": \"可选 schema key\",\n"
            "      \"caution\": \"可选风险提示（中文）\"\n"
            "    }\n"
            "  ]\n"
            "}"
        )
    else:
        system = (
            "You are LogicKG Config Assistant. Return STRICT JSON only.\n"
            "Produce operational tuning suggestions for the user's optimization goal.\n"
            "Each suggestion MUST use an anchor from the allowed anchors list.\n"
            "Keep suggestions concrete, short, and actionable.\n"
        )
        user = (
            f"Goal:\n{goal}\n\n"
            f"Max suggestions: {max_items}\n\n"
            f"Allowed anchors:\n{allowed_anchors}\n\n"
            f"Current profile JSON:\n{profile}\n\n"
            "Output JSON schema:\n"
            "{\n"
            "  \"suggestions\": [\n"
            "    {\n"
            "      \"module\": \"discovery|similarity|schema\",\n"
            "      \"key\": \"parameter_name\",\n"
            "      \"anchor\": \"one_of_allowed_anchors\",\n"
            "      \"suggested_value\": \"new value or concise change\",\n"
            "      \"rationale\": \"why this helps\",\n"
            "      \"focus_key\": \"optional schema key\",\n"
            "      \"caution\": \"optional risk\"\n"
            "    }\n"
            "  ]\n"
            "}"
        )
    try:
        parsed = call_validated_json(system=system, user=user, model_class=_LLMSuggestionResponse, max_retries=1)
    except Exception:
        return None

    anchor_set = set(allowed_anchors)
    normalized: list[dict[str, Any]] = []
    for item in parsed.suggestions:
        if item.anchor not in anchor_set:
            continue
        normalized.append(item.model_dump())
    if not normalized:
        return None
    return normalized[:max_items]


@router.get("/profile")
def get_config_center_profile():
    profile = load_profile()
    return {"profile": profile}


@router.put("/profile")
def update_config_center_profile(req: ConfigCenterProfileUpdateRequest):
    try:
        current = load_profile()
        modules = current.get("modules") if isinstance(current.get("modules"), dict) else {}
        next_modules = dict(modules) if isinstance(modules, dict) else {}
        incoming = req.modules if isinstance(req.modules, dict) else {}
        if isinstance(incoming.get("discovery"), dict):
            next_modules["discovery"] = normalize_discovery_config(
                incoming.get("discovery"),
                base=next_modules.get("discovery") if isinstance(next_modules.get("discovery"), dict) else None,
            )
        if isinstance(incoming.get("similarity"), dict):
            next_modules["similarity"] = normalize_similarity_config(
                incoming.get("similarity"),
                base=next_modules.get("similarity") if isinstance(next_modules.get("similarity"), dict) else None,
            )
        merged = normalize_profile({"version": current.get("version"), "modules": next_modules})
        saved = save_profile(merged)
        return {"ok": True, "profile": saved}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/catalog")
def get_config_center_catalog():
    profile = load_profile()
    return _catalog(profile)


@router.post("/assistant")
def run_config_center_assistant(req: ConfigAssistantRequest):
    goal = req.goal.strip()
    locale = _normalize_locale(req.locale)
    profile = load_profile()
    catalog = _catalog(profile)

    llm_rows = _llm_suggestions(goal, profile, catalog, req.max_suggestions, locale=locale)
    used_llm = bool(llm_rows)
    rows = llm_rows or _heuristic_suggestions(goal, profile, req.max_suggestions, locale=locale)
    try:
        suggestions = [ConfigAssistantSuggestion.model_validate(item).model_dump() for item in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to format assistant output: {exc}") from exc

    return {
        "goal": goal,
        "locale": locale,
        "used_llm": used_llm,
        "suggestions": suggestions,
        "profile_version": profile.get("version"),
    }


@router.get("/effective/discovery")
def get_effective_discovery_defaults():
    return {"discovery": merge_discovery_config({})}


@router.get("/effective/similarity")
def get_effective_similarity_defaults():
    return {"similarity": merge_similarity_config({})}
