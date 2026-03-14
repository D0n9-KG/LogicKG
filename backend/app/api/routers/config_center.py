from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.llm.client import test_llm_worker_connection
from app.ops_config_store import (
    apply_profile_to_settings,
    merge_community_config,
    merge_infra_config,
    merge_integrations_config,
    merge_providers_config,
    load_profile,
    merge_runtime_config,
    merge_similarity_config,
    normalize_community_config,
    normalize_infra_config,
    normalize_integrations_config,
    normalize_llm_workers_config,
    normalize_profile,
    normalize_providers_config,
    normalize_runtime_config,
    normalize_similarity_config,
    save_profile,
)
from app.schema_store import load_active


router = APIRouter(prefix="/config-center", tags=["config-center"])


SIMILARITY_FIELD_HELP: dict[str, str] = {
    "group_clustering_method": "Grouping method for similarity clusters.",
    "group_clustering_threshold": "Similarity threshold used when forming retrieval clusters.",
}

RUNTIME_FIELD_HELP: dict[str, str] = {
    "ingest_llm_max_workers": "Effective paper-level ingest concurrency derived from enabled LLM workers, per-paper fan-out, and the global LLM limit.",
    "phase1_chunk_claim_max_workers": "Parallel claim-batch workers inside one paper extraction task.",
    "phase1_grounding_max_workers": "Parallel grounding judge workers for claim evidence verification.",
    "phase2_conflict_max_workers": "Parallel conflict-judge workers for semantic contradiction checks.",
    "ingest_pre_llm_max_workers": "Parallel preprocessing workers for reference and citation-event recovery.",
    "faiss_embed_max_workers": "Parallel embedding workers when rebuilding global FAISS indexes.",
    "llm_global_max_concurrent": "Global cap for in-flight LLM calls across the whole backend process.",
}

PROVIDERS_FIELD_HELP: dict[str, str] = {
    "embedding_provider": "Embedding provider used for RAG, FAISS, and clustering.",
    "embedding_base_url": "Optional override for the embedding provider base URL.",
    "embedding_api_key": "Generic embedding API key override.",
    "embedding_model": "Default embedding model used for vector indexing and retrieval.",
    "siliconflow_api_key": "SiliconFlow embedding API key.",
}

LLM_WORKERS_FIELD_HELP: dict[str, str] = {
    "label": "Friendly worker label shown in the operations UI.",
    "base_url": "OpenAI-compatible base URL used by this worker.",
    "api_key": "API key used for requests routed to this worker.",
    "model": "Optional model override for this worker. Falls back to the global default when empty.",
    "max_concurrent": "Paper-level capacity and per-worker request limiter for this worker.",
    "enabled": "Whether this worker can receive new paper extraction jobs.",
}

INFRA_FIELD_HELP: dict[str, str] = {
    "neo4j_uri": "Neo4j Bolt URI for the graph database.",
    "neo4j_user": "Neo4j username.",
    "neo4j_password": "Neo4j password.",
    "pageindex_enabled": "Whether PageIndex-backed PDF lookup is enabled.",
    "pageindex_index_dir": "Directory for PageIndex artifacts.",
    "data_root": "Project data root used for relative storage resolution.",
    "storage_dir": "Backend storage directory for papers, derived data, and ops config.",
    "autoyoutu_dir": "Path to the AutoYoutu project checkout.",
    "youtu_ssh_host": "SSH host for remote Youtu execution.",
    "youtu_ssh_user": "SSH user for remote Youtu execution.",
    "youtu_ssh_key_path": "SSH private key path for remote Youtu execution.",
    "textbook_youtu_schema": "AutoYoutu schema used for textbook extraction.",
    "textbook_chapter_max_tokens": "Soft token cap used when chunking textbook chapters.",
}

INTEGRATIONS_FIELD_HELP: dict[str, str] = {
    "crossref_mailto": "Contact email for Crossref polite-pool requests.",
    "crossref_user_agent": "User-Agent prefix sent to Crossref.",
}

COMMUNITY_FIELD_HELP: dict[str, str] = {
    "global_community_version": "Version label for the global community index.",
    "global_community_max_nodes": "Maximum node count projected into the global community graph.",
    "global_community_max_edges": "Maximum edge count projected into the global community graph.",
    "global_community_top_keywords": "Number of keywords stored per global community.",
    "global_community_tree_comm_embedding_model": "Embedding model used by TreeComm community building.",
    "global_community_tree_comm_struct_weight": "Relative structural weight used by TreeComm (0 = semantic only, 1 = structure only).",
}

SECRET_FIELDS = {
    "providers.llm_api_key",
    "providers.deepseek_api_key",
    "providers.openrouter_api_key",
    "providers.openai_api_key",
    "providers.embedding_api_key",
    "providers.siliconflow_api_key",
    "llm_workers.api_key",
    "infra.neo4j_password",
}

SELECT_OPTIONS: dict[str, list[str]] = {
    "providers.llm_provider": ["deepseek", "openrouter", "openai"],
    "providers.embedding_provider": ["", "siliconflow", "openai", "openrouter", "deepseek"],
}

NUMBER_FIELD_META: dict[str, dict[str, float]] = {
    "runtime.ingest_llm_max_workers": {"min": 1, "max": 16, "step": 1},
    "llm_workers.max_concurrent": {"min": 1, "max": 16, "step": 1},
    "infra.textbook_chapter_max_tokens": {"min": 1000, "max": 64000, "step": 500},
    "community.global_community_max_nodes": {"min": 100, "max": 500000, "step": 100},
    "community.global_community_max_edges": {"min": 100, "max": 1000000, "step": 100},
    "community.global_community_top_keywords": {"min": 1, "max": 50, "step": 1},
    "community.global_community_tree_comm_struct_weight": {"min": 0, "max": 1, "step": 0.05},
}

BOOLEAN_FIELDS = {
    "llm_workers.enabled",
    "infra.pageindex_enabled",
}

READ_ONLY_FIELDS = {
    "runtime.ingest_llm_max_workers",
}


class ConfigCenterProfileUpdateRequest(BaseModel):
    modules: dict[str, Any] = Field(default_factory=dict)


class ConfigAssistantRequest(BaseModel):
    goal: str = Field(min_length=2, max_length=2000)
    max_suggestions: int = Field(default=8, ge=1, le=20)
    locale: str | None = Field(default=None, description="UI locale hint (zh-CN / en-US).")


class ConfigLlmWorkerTestRequest(BaseModel):
    worker: dict[str, Any] = Field(default_factory=dict)


class ConfigAssistantSuggestion(BaseModel):
    module: str
    key: str
    anchor: str
    suggested_value: str
    rationale: str
    focus_key: str | None = None
    caution: str | None = None


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
    rule_keys = sorted(str(key) for key in rules.keys() if str(key).strip())
    prompt_keys = sorted(str(key) for key in prompts.keys() if str(key).strip())
    return rule_keys, prompt_keys


def _catalog(profile: dict[str, Any]) -> dict[str, Any]:
    modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
    similarity = modules.get("similarity") if isinstance(modules.get("similarity"), dict) else {}
    runtime = modules.get("runtime") if isinstance(modules.get("runtime"), dict) else {}
    providers = modules.get("providers") if isinstance(modules.get("providers"), dict) else {}
    llm_workers = modules.get("llm_workers") if isinstance(modules.get("llm_workers"), dict) else {}
    infra = modules.get("infra") if isinstance(modules.get("infra"), dict) else {}
    integrations = modules.get("integrations") if isinstance(modules.get("integrations"), dict) else {}
    community = modules.get("community") if isinstance(modules.get("community"), dict) else {}
    rule_keys, prompt_keys = _schema_key_catalog()

    def _field_rows(module_id: str, current: dict[str, Any], help_map: dict[str, str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for key, desc in help_map.items():
            anchor = f"{module_id}.{key}"
            row = {
                "key": key,
                "anchor": anchor,
                "description": desc,
                "current_value": current.get(key),
                "label": key,
            }
            if anchor in SECRET_FIELDS:
                row["secret"] = True
                row["input_type"] = "password"
            if anchor in BOOLEAN_FIELDS:
                row["type"] = "boolean"
            if anchor in SELECT_OPTIONS:
                row["type"] = "select"
                row["options"] = [{"value": item, "label": item or "(empty)"} for item in SELECT_OPTIONS[anchor]]
            if anchor in NUMBER_FIELD_META:
                row["type"] = "number"
                row.update(NUMBER_FIELD_META[anchor])
            if anchor in READ_ONLY_FIELDS:
                row["read_only"] = True
            rows.append(row)
        return rows

    return {
        "modules": [
            {
                "id": "similarity",
                "label": "Similarity & Clustering",
                "fields": _field_rows("similarity", similarity, SIMILARITY_FIELD_HELP),
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
            {
                "id": "runtime",
                "label": "Runtime Concurrency",
                "description": "Per-paper fan-out, preprocessing, and global limiters. Paper-level parallelism is derived from enabled LLM workers.",
                "fields": _field_rows("runtime", runtime, RUNTIME_FIELD_HELP),
            },
            {
                "id": "providers",
                "label": "LLM & Embeddings",
                "description": "Embedding-related settings. Whole-paper LLM routing now lives on the LLM worker list.",
                "fields": _field_rows("providers", providers, PROVIDERS_FIELD_HELP),
            },
            {
                "id": "llm_workers",
                "label": "LLM Workers",
                "description": "Bind whole-paper extraction jobs to independently configured LLM gateways. .env single-provider settings remain as the fallback path.",
                "fields": _field_rows("llm_workers", {}, LLM_WORKERS_FIELD_HELP),
                "items": list(llm_workers.get("items") or []),
            },
            {
                "id": "infra",
                "label": "Infrastructure",
                "description": "Graph database, storage, and textbook execution settings. Core connection changes are safest after a backend restart.",
                "fields": _field_rows("infra", infra, INFRA_FIELD_HELP),
            },
            {
                "id": "integrations",
                "label": "External Integrations",
                "description": "Crossref and other external service identifiers. Environment variables still override saved values.",
                "fields": _field_rows("integrations", integrations, INTEGRATIONS_FIELD_HELP),
            },
            {
                "id": "community",
                "label": "Global Community",
                "description": "Global community clustering limits and TreeComm parameters. Large changes are best paired with a manual community rebuild.",
                "fields": _field_rows("community", community, COMMUNITY_FIELD_HELP),
            },
        ]
    }


def _text_by_locale(locale: str, zh: str, en: str) -> str:
    return zh if locale == "zh-CN" else en


def _normalized_goal_text(goal: str) -> str:
    return " ".join(str(goal or "").strip().lower().split())


def _goal_mentions_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


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
    if any(item.get("_sig") == signature for item in out):
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


def _heuristic_suggestions(
    goal: str,
    profile: dict[str, Any],
    max_items: int,
    *,
    locale: str = "en-US",
) -> list[dict[str, Any]]:
    normalized_locale = _normalize_locale(locale)
    text = _normalized_goal_text(goal)
    modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
    similarity = normalize_similarity_config(modules.get("similarity") if isinstance(modules.get("similarity"), dict) else {})
    runtime = normalize_runtime_config(modules.get("runtime") if isinstance(modules.get("runtime"), dict) else {})

    precision_tokens = (
        "precision",
        "strict",
        "noise",
        "hallucination",
        "extract",
        "extraction",
        "citation",
        "knowledge graph",
        "准确",
        "精确",
        "精准",
        "噪声",
        "抽取",
        "引用",
        "图谱",
    )
    recall_tokens = (
        "coverage",
        "broader",
        "explore",
        "diversity",
        "召回",
        "覆盖",
        "更多",
        "发散",
    )
    speed_tokens = (
        "latency",
        "faster",
        "cost",
        "cheap",
        "速度",
        "耗时",
        "成本",
        "更快",
        "更省",
    )

    wants_precision = _goal_mentions_any(text, precision_tokens)
    wants_recall = _goal_mentions_any(text, recall_tokens)
    wants_speed = _goal_mentions_any(text, speed_tokens)

    out: list[dict[str, Any]] = []

    if wants_precision:
        _add_suggestion(
            out,
            module="similarity",
            key="group_clustering_threshold",
            anchor="similarity.group_clustering_threshold",
            suggested_value=f"{min(0.95, float(similarity['group_clustering_threshold']) + 0.03):.2f}",
            rationale=_text_by_locale(
                normalized_locale,
                "提高聚类阈值，让相似簇更紧，减少语义漂移。",
                "Raise the clustering threshold to tighten semantic groups and reduce drift.",
            ),
        )
        _add_suggestion(
            out,
            module="schema",
            key="rules_json",
            anchor="schema.rules_json",
            suggested_value="0.60",
            rationale=_text_by_locale(
                normalized_locale,
                "提高 grounded claim 通过下限，增强抽取精度。",
                "Raise the grounded-claim gate to improve extraction precision.",
            ),
            focus_key="phase1_gate_supported_ratio_min",
        )
        _add_suggestion(
            out,
            module="schema",
            key="prompts_json",
            anchor="schema.prompts_json",
            suggested_value=_text_by_locale(
                normalized_locale,
                "强化只基于证据生成主张的约束。",
                "Strengthen evidence-only claim generation constraints.",
            ),
            rationale=_text_by_locale(
                normalized_locale,
                "收紧抽取提示词，减少无证据支撑的输出。",
                "Tighten extraction prompts to reduce unsupported output.",
            ),
            focus_key="phase1_chunk_claim_extract_system",
        )

    if wants_recall:
        _add_suggestion(
            out,
            module="similarity",
            key="group_clustering_method",
            anchor="similarity.group_clustering_method",
            suggested_value="hybrid",
            rationale=_text_by_locale(
                normalized_locale,
                "混合聚类更适合在稳定性和覆盖面之间取平衡。",
                "Hybrid clustering balances stable neighborhoods with broader coverage.",
            ),
        )
        _add_suggestion(
            out,
            module="schema",
            key="rules_json",
            anchor="schema.rules_json",
            suggested_value="0.45",
            rationale=_text_by_locale(
                normalized_locale,
                "适度降低 supported ratio 下限，为后续过滤保留更多候选主张。",
                "Lower the supported-ratio gate slightly to preserve more candidate claims for later filtering.",
            ),
            focus_key="phase1_gate_supported_ratio_min",
            caution=_text_by_locale(
                normalized_locale,
                "阈值过低会增加噪声，需要更强的后续审核。",
                "A lower gate can increase noise and may require stronger downstream review.",
            ),
        )

    if wants_speed:
        _add_suggestion(
            out,
            module="runtime",
            key="llm_global_max_concurrent",
            anchor="runtime.llm_global_max_concurrent",
            suggested_value=str(min(20, int(runtime.get("llm_global_max_concurrent") or 12) + 2)),
            rationale=_text_by_locale(
                normalized_locale,
                "全局并发上限需要和已启用工作器的总容量一起配合，避免请求在统一信号量上排长队。",
                "The global concurrency cap should grow with the enabled worker capacity so requests do not spend their time queueing on one semaphore.",
            ),
            caution=_text_by_locale(
                normalized_locale,
                "该参数会影响全局 LLM 限流，通常需要重启后端才能完全清掉旧信号量状态。",
                "This affects the global LLM limiter and typically needs a backend restart to fully clear old semaphore state.",
            ),
        )
        _add_suggestion(
            out,
            module="similarity",
            key="group_clustering_method",
            anchor="similarity.group_clustering_method",
            suggested_value="agglomerative",
            rationale=_text_by_locale(
                normalized_locale,
                "更轻量的聚类方式有助于降低构建成本。",
                "A lighter clustering mode can reduce rebuild cost.",
            ),
        )
        _add_suggestion(
            out,
            module="schema",
            key="prompts_json",
            anchor="schema.prompts_json",
            suggested_value=_text_by_locale(
                normalized_locale,
                "减少冗长解释，优先结构化输出。",
                "Reduce verbose instructions and favor compact structured output.",
            ),
            rationale=_text_by_locale(
                normalized_locale,
                "提示词更紧凑时，通常能降低抽取延迟。",
                "More compact prompts often lower extraction latency.",
            ),
            focus_key="logic_claims_system",
        )

    if not out:
        _add_suggestion(
            out,
            module="similarity",
            key="group_clustering_threshold",
            anchor="similarity.group_clustering_threshold",
            suggested_value=f"{float(similarity['group_clustering_threshold']):.2f}",
            rationale=_text_by_locale(
                normalized_locale,
                "聚类阈值会直接影响相似簇粒度以及下游检索质量。",
                "Cluster threshold directly affects similarity-group granularity and downstream retrieval quality.",
            ),
        )
        _add_suggestion(
            out,
            module="schema",
            key="rules_json",
            anchor="schema.rules_json",
            suggested_value=_text_by_locale(normalized_locale, "建议复核", "Review"),
            rationale=_text_by_locale(
                normalized_locale,
                "先校准抽取门限，再决定是否调整更多参数。",
                "Calibrate extraction gates first before changing more knobs.",
            ),
            focus_key="phase1_gate_supported_ratio_min",
        )
        _add_suggestion(
            out,
            module="schema",
            key="prompts_json",
            anchor="schema.prompts_json",
            suggested_value=_text_by_locale(normalized_locale, "建议复核", "Review"),
            rationale=_text_by_locale(
                normalized_locale,
                "当偏差主要来自语义表达时，优先复核提示词约束。",
                "When behavior drift is mostly semantic, review prompt constraints first.",
            ),
            focus_key="logic_claims_system",
        )

    cleaned = [{key: value for key, value in row.items() if key != "_sig"} for row in out]
    return cleaned[:max_items]


@router.get("/profile")
def get_config_center_profile():
    return {"profile": load_profile()}


@router.put("/profile")
def update_config_center_profile(req: ConfigCenterProfileUpdateRequest):
    try:
        current = load_profile()
        modules = current.get("modules") if isinstance(current.get("modules"), dict) else {}
        next_modules = dict(modules) if isinstance(modules, dict) else {}
        incoming = req.modules if isinstance(req.modules, dict) else {}
        if isinstance(incoming.get("similarity"), dict):
            next_modules["similarity"] = normalize_similarity_config(
                incoming.get("similarity"),
                base=next_modules.get("similarity") if isinstance(next_modules.get("similarity"), dict) else None,
            )
        if isinstance(incoming.get("runtime"), dict):
            next_modules["runtime"] = normalize_runtime_config(
                incoming.get("runtime"),
                base=next_modules.get("runtime") if isinstance(next_modules.get("runtime"), dict) else None,
            )
        if isinstance(incoming.get("providers"), dict):
            next_modules["providers"] = normalize_providers_config(
                incoming.get("providers"),
                base=next_modules.get("providers") if isinstance(next_modules.get("providers"), dict) else None,
            )
        if isinstance(incoming.get("llm_workers"), dict):
            next_modules["llm_workers"] = normalize_llm_workers_config(
                incoming.get("llm_workers"),
                base=next_modules.get("llm_workers") if isinstance(next_modules.get("llm_workers"), dict) else None,
            )
        if isinstance(incoming.get("infra"), dict):
            next_modules["infra"] = normalize_infra_config(
                incoming.get("infra"),
                base=next_modules.get("infra") if isinstance(next_modules.get("infra"), dict) else None,
            )
        if isinstance(incoming.get("integrations"), dict):
            next_modules["integrations"] = normalize_integrations_config(
                incoming.get("integrations"),
                base=next_modules.get("integrations") if isinstance(next_modules.get("integrations"), dict) else None,
            )
        if isinstance(incoming.get("community"), dict):
            next_modules["community"] = normalize_community_config(
                incoming.get("community"),
                base=next_modules.get("community") if isinstance(next_modules.get("community"), dict) else None,
            )
        merged = normalize_profile({"version": current.get("version"), "modules": next_modules})
        saved = save_profile(merged)
        apply_profile_to_settings(saved)
        return {"ok": True, "profile": saved}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/catalog")
def get_config_center_catalog():
    return _catalog(load_profile())


@router.post("/llm-workers/test")
def run_config_center_llm_worker_test(req: ConfigLlmWorkerTestRequest):
    try:
        items = normalize_llm_workers_config({"items": [req.worker]}).get("items") or []
        if not items:
            raise ValueError("Worker payload missing")
        worker = items[0]
        result = test_llm_worker_connection(worker)
        return {
            "ok": True,
            "reachable": bool(result.get("ok")),
            "error": str(result.get("error") or "").strip() or None,
            "worker": {
                "id": str(worker.get("id") or "").strip(),
                "label": str(worker.get("label") or "").strip(),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/assistant")
def run_config_center_assistant(req: ConfigAssistantRequest):
    goal = req.goal.strip()
    locale = _normalize_locale(req.locale)
    profile = load_profile()
    rows = _heuristic_suggestions(goal, profile, req.max_suggestions, locale=locale)
    try:
        suggestions = [ConfigAssistantSuggestion.model_validate(item).model_dump() for item in rows]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to format assistant output: {exc}") from exc

    return {
        "goal": goal,
        "locale": locale,
        "used_llm": False,
        "suggestions": suggestions,
        "profile_version": profile.get("version"),
    }


@router.get("/effective/similarity")
def get_effective_similarity_defaults():
    return {"similarity": merge_similarity_config({})}


@router.get("/effective/runtime")
def get_effective_runtime_defaults():
    return {"runtime": merge_runtime_config({})}


@router.get("/effective/providers")
def get_effective_provider_defaults():
    return {"providers": merge_providers_config({})}


@router.get("/effective/infra")
def get_effective_infra_defaults():
    return {"infra": merge_infra_config({})}


@router.get("/effective/integrations")
def get_effective_integration_defaults():
    return {"integrations": merge_integrations_config({})}


@router.get("/effective/community")
def get_effective_community_defaults():
    return {"community": merge_community_config({})}
