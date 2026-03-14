from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from app.settings import settings


_SIMILARITY_METHODS = {"agglomerative", "louvain", "hybrid"}
_PROVIDER_CHOICES = {"deepseek", "openrouter", "openai"}
_EMBEDDING_PROVIDER_CHOICES = {"", "siliconflow", "openai", "openrouter", "deepseek"}
_LLM_WORKER_INT_LIMITS: dict[str, tuple[int, int, int]] = {
    "max_concurrent": (32, 1, 128),
}

_RUNTIME_LIMITS: dict[str, tuple[int, int, int]] = {
    "ingest_llm_max_workers": (5, 1, 32),
    "phase1_chunk_claim_max_workers": (4, 1, 8),
    "phase1_grounding_max_workers": (3, 1, 6),
    "phase2_conflict_max_workers": (3, 1, 6),
    "ingest_pre_llm_max_workers": (6, 1, 8),
    "faiss_embed_max_workers": (4, 1, 6),
    "llm_global_max_concurrent": (32, 1, 256),
    "ingest_llm_heartbeat_seconds": (20, 5, 300),
    "llm_timeout_seconds": (60, 10, 600),
    "llm_client_max_retries": (0, 0, 5),
    "rag_llm_timeout_seconds": (45, 10, 180),
    "rag_llm_max_tokens": (900, 128, 4096),
    "crossref_max_concurrent": (2, 1, 3),
}
_RUNTIME_FLOAT_LIMITS: dict[str, tuple[float, float, float]] = {
    "neo4j_connection_timeout_seconds": (15.0, 1.0, 120.0),
    "crossref_min_interval_seconds": (0.12, 0.0, 5.0),
}
_RUNTIME_BOOL_FIELDS = {"phase1_gate_allow_weak"}
_COMMUNITY_INT_LIMITS: dict[str, tuple[int, int, int]] = {
    "global_community_max_nodes": (50000, 100, 500000),
    "global_community_max_edges": (100000, 100, 1000000),
    "global_community_top_keywords": (8, 1, 50),
}
_COMMUNITY_FLOAT_LIMITS: dict[str, tuple[float, float, float]] = {
    "global_community_tree_comm_struct_weight": (0.3, 0.0, 1.0),
}

_PROVIDERS_FIELDS = (
    "llm_provider",
    "llm_base_url",
    "llm_api_key",
    "llm_model",
    "deepseek_api_key",
    "openrouter_api_key",
    "openai_api_key",
    "embedding_provider",
    "embedding_base_url",
    "embedding_api_key",
    "embedding_model",
    "siliconflow_api_key",
)
_LLM_WORKER_FIELDS = (
    "id",
    "label",
    "base_url",
    "api_key",
    "model",
    "max_concurrent",
    "enabled",
)
_INFRA_FIELDS = (
    "neo4j_uri",
    "neo4j_user",
    "neo4j_password",
    "pageindex_enabled",
    "pageindex_index_dir",
    "data_root",
    "storage_dir",
    "autoyoutu_dir",
    "youtu_ssh_host",
    "youtu_ssh_user",
    "youtu_ssh_key_path",
    "textbook_youtu_schema",
    "textbook_chapter_max_tokens",
)
_INTEGRATIONS_FIELDS = (
    "crossref_mailto",
    "crossref_user_agent",
)
_COMMUNITY_FIELDS = (
    "global_community_version",
    "global_community_max_nodes",
    "global_community_max_edges",
    "global_community_top_keywords",
    "global_community_tree_comm_embedding_model",
    "global_community_tree_comm_struct_weight",
)

_FIELD_ENV_KEYS: dict[str, tuple[str, ...]] = {
    "neo4j_uri": ("NEO4J_URI",),
    "neo4j_user": ("NEO4J_USER", "NEO4J_USERNAME"),
    "neo4j_password": ("NEO4J_PASSWORD",),
    "llm_provider": ("LLM_PROVIDER",),
    "llm_base_url": ("LLM_BASE_URL",),
    "llm_api_key": ("LLM_API_KEY",),
    "llm_model": ("LLM_MODEL",),
    "deepseek_api_key": ("DEEPSEEK_API_KEY", "DEEPSEEK_KEY"),
    "openrouter_api_key": ("OPENROUTER_API_KEY", "OPENROUTER_KEY"),
    "openai_api_key": ("OPENAI_API_KEY",),
    "embedding_provider": ("EMBEDDING_PROVIDER",),
    "embedding_base_url": ("EMBEDDING_BASE_URL",),
    "embedding_api_key": ("EMBEDDING_API_KEY",),
    "embedding_model": ("EMBEDDING_MODEL",),
    "siliconflow_api_key": ("SILICONFLOW_API_KEY", "SILICON_FLOW_API_KEY", "SILICONCLOUD_API_KEY"),
    "phase1_gate_allow_weak": ("PHASE1_GATE_ALLOW_WEAK",),
    "group_clustering_threshold": ("GROUP_CLUSTERING_THRESHOLD",),
    "group_clustering_method": ("GROUP_CLUSTERING_METHOD",),
    "ingest_llm_max_workers": ("INGEST_LLM_MAX_WORKERS",),
    "ingest_llm_heartbeat_seconds": ("INGEST_LLM_HEARTBEAT_SECONDS",),
    "llm_timeout_seconds": ("LLM_TIMEOUT_SECONDS",),
    "llm_client_max_retries": ("LLM_CLIENT_MAX_RETRIES",),
    "rag_llm_timeout_seconds": ("RAG_LLM_TIMEOUT_SECONDS",),
    "rag_llm_max_tokens": ("RAG_LLM_MAX_TOKENS",),
    "pageindex_enabled": ("PAGEINDEX_ENABLED",),
    "pageindex_index_dir": ("PAGEINDEX_INDEX_DIR",),
    "neo4j_connection_timeout_seconds": ("NEO4J_CONNECTION_TIMEOUT_SECONDS",),
    "phase1_chunk_claim_max_workers": ("PHASE1_CHUNK_CLAIM_MAX_WORKERS",),
    "phase1_grounding_max_workers": ("PHASE1_GROUNDING_MAX_WORKERS",),
    "phase2_conflict_max_workers": ("PHASE2_CONFLICT_MAX_WORKERS",),
    "ingest_pre_llm_max_workers": ("INGEST_PRE_LLM_MAX_WORKERS",),
    "faiss_embed_max_workers": ("FAISS_EMBED_MAX_WORKERS",),
    "llm_global_max_concurrent": ("LLM_GLOBAL_MAX_CONCURRENT",),
    "crossref_mailto": ("CROSSREF_MAILTO",),
    "crossref_user_agent": ("CROSSREF_USER_AGENT",),
    "crossref_max_concurrent": ("CROSSREF_MAX_CONCURRENT",),
    "crossref_min_interval_seconds": ("CROSSREF_MIN_INTERVAL_SECONDS",),
    "data_root": ("DATA_ROOT",),
    "storage_dir": ("STORAGE_DIR",),
    "autoyoutu_dir": ("AUTOYOUTU_DIR",),
    "youtu_ssh_host": ("YOUTU_SSH_HOST",),
    "youtu_ssh_user": ("YOUTU_SSH_USER",),
    "youtu_ssh_key_path": ("YOUTU_SSH_KEY_PATH",),
    "textbook_youtu_schema": ("TEXTBOOK_YOUTU_SCHEMA",),
    "textbook_chapter_max_tokens": ("TEXTBOOK_CHAPTER_MAX_TOKENS",),
    "global_community_version": ("GLOBAL_COMMUNITY_VERSION",),
    "global_community_max_nodes": ("GLOBAL_COMMUNITY_MAX_NODES",),
    "global_community_max_edges": ("GLOBAL_COMMUNITY_MAX_EDGES",),
    "global_community_top_keywords": ("GLOBAL_COMMUNITY_TOP_KEYWORDS",),
    "global_community_tree_comm_embedding_model": ("GLOBAL_COMMUNITY_TREE_COMM_EMBEDDING_MODEL",),
    "global_community_tree_comm_struct_weight": ("GLOBAL_COMMUNITY_TREE_COMM_STRUCT_WEIGHT",),
}

# Test hook: allow overriding storage path without mutating global settings.
_CONFIG_PATH_OVERRIDE: Path | None = None


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _config_path() -> Path:
    if _CONFIG_PATH_OVERRIDE is not None:
        p = Path(_CONFIG_PATH_OVERRIDE)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    p = _backend_root() / settings.storage_dir / "ops" / "config_center.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _clamp_int(value: Any, *, default: int, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except Exception:
        v = int(default)
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _clamp_float(value: Any, *, default: float, lo: float, hi: float) -> float:
    try:
        v = float(value)
    except Exception:
        v = float(default)
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _as_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        t = value.strip().lower()
        if t in {"1", "true", "yes", "on"}:
            return True
        if t in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return bool(default)


def _as_text(value: Any, *, default: str = "") -> str:
    if value is None:
        return str(default)
    return str(value).strip()


def _default_similarity() -> dict[str, Any]:
    return {
        "group_clustering_method": str(getattr(settings, "group_clustering_method", "hybrid") or "hybrid"),
        "group_clustering_threshold": float(getattr(settings, "group_clustering_threshold", 0.85) or 0.85),
    }


def _default_runtime() -> dict[str, Any]:
    return {
        "ingest_llm_max_workers": int(getattr(settings, "ingest_llm_max_workers", _RUNTIME_LIMITS["ingest_llm_max_workers"][0])),
        "phase1_chunk_claim_max_workers": int(
            getattr(settings, "phase1_chunk_claim_max_workers", _RUNTIME_LIMITS["phase1_chunk_claim_max_workers"][0])
        ),
        "phase1_grounding_max_workers": int(
            getattr(settings, "phase1_grounding_max_workers", _RUNTIME_LIMITS["phase1_grounding_max_workers"][0])
        ),
        "phase2_conflict_max_workers": int(
            getattr(settings, "phase2_conflict_max_workers", _RUNTIME_LIMITS["phase2_conflict_max_workers"][0])
        ),
        "ingest_pre_llm_max_workers": int(
            getattr(settings, "ingest_pre_llm_max_workers", _RUNTIME_LIMITS["ingest_pre_llm_max_workers"][0])
        ),
        "faiss_embed_max_workers": int(getattr(settings, "faiss_embed_max_workers", _RUNTIME_LIMITS["faiss_embed_max_workers"][0])),
        "llm_global_max_concurrent": int(
            getattr(settings, "llm_global_max_concurrent", _RUNTIME_LIMITS["llm_global_max_concurrent"][0])
        ),
        "ingest_llm_heartbeat_seconds": int(
            getattr(settings, "ingest_llm_heartbeat_seconds", _RUNTIME_LIMITS["ingest_llm_heartbeat_seconds"][0])
        ),
        "llm_timeout_seconds": int(getattr(settings, "llm_timeout_seconds", _RUNTIME_LIMITS["llm_timeout_seconds"][0])),
        "llm_client_max_retries": int(
            getattr(settings, "llm_client_max_retries", _RUNTIME_LIMITS["llm_client_max_retries"][0])
        ),
        "rag_llm_timeout_seconds": int(
            getattr(settings, "rag_llm_timeout_seconds", _RUNTIME_LIMITS["rag_llm_timeout_seconds"][0])
        ),
        "rag_llm_max_tokens": int(getattr(settings, "rag_llm_max_tokens", _RUNTIME_LIMITS["rag_llm_max_tokens"][0])),
        "neo4j_connection_timeout_seconds": float(
            getattr(settings, "neo4j_connection_timeout_seconds", _RUNTIME_FLOAT_LIMITS["neo4j_connection_timeout_seconds"][0])
        ),
        "crossref_max_concurrent": int(
            getattr(settings, "crossref_max_concurrent", _RUNTIME_LIMITS["crossref_max_concurrent"][0])
        ),
        "crossref_min_interval_seconds": float(
            getattr(settings, "crossref_min_interval_seconds", _RUNTIME_FLOAT_LIMITS["crossref_min_interval_seconds"][0])
        ),
        "phase1_gate_allow_weak": bool(getattr(settings, "phase1_gate_allow_weak", False)),
    }


def _default_providers() -> dict[str, Any]:
    return {
        "llm_provider": _as_text(getattr(settings, "llm_provider", "deepseek"), default="deepseek"),
        "llm_base_url": _as_text(getattr(settings, "llm_base_url", None)),
        "llm_api_key": _as_text(getattr(settings, "llm_api_key", None)),
        "llm_model": _as_text(getattr(settings, "llm_model", "deepseek-chat"), default="deepseek-chat"),
        "deepseek_api_key": _as_text(getattr(settings, "deepseek_api_key", None)),
        "openrouter_api_key": _as_text(getattr(settings, "openrouter_api_key", None)),
        "openai_api_key": _as_text(getattr(settings, "openai_api_key", None)),
        "embedding_provider": _as_text(getattr(settings, "embedding_provider", None)),
        "embedding_base_url": _as_text(getattr(settings, "embedding_base_url", None)),
        "embedding_api_key": _as_text(getattr(settings, "embedding_api_key", None)),
        "embedding_model": _as_text(getattr(settings, "embedding_model", "text-embedding-3-small"), default="text-embedding-3-small"),
        "siliconflow_api_key": _as_text(getattr(settings, "siliconflow_api_key", None)),
    }


def _default_infra() -> dict[str, Any]:
    return {
        "neo4j_uri": _as_text(getattr(settings, "neo4j_uri", "bolt://localhost:7687"), default="bolt://localhost:7687"),
        "neo4j_user": _as_text(getattr(settings, "neo4j_user", "neo4j"), default="neo4j"),
        "neo4j_password": _as_text(getattr(settings, "neo4j_password", "neo4j_password"), default="neo4j_password"),
        "pageindex_enabled": bool(getattr(settings, "pageindex_enabled", False)),
        "pageindex_index_dir": _as_text(getattr(settings, "pageindex_index_dir", "storage/pageindex"), default="storage/pageindex"),
        "data_root": _as_text(getattr(settings, "data_root", ".."), default=".."),
        "storage_dir": _as_text(getattr(settings, "storage_dir", "storage"), default="storage"),
        "autoyoutu_dir": _as_text(getattr(settings, "autoyoutu_dir", "")),
        "youtu_ssh_host": _as_text(getattr(settings, "youtu_ssh_host", "")),
        "youtu_ssh_user": _as_text(getattr(settings, "youtu_ssh_user", "")),
        "youtu_ssh_key_path": _as_text(getattr(settings, "youtu_ssh_key_path", "")),
        "textbook_youtu_schema": _as_text(getattr(settings, "textbook_youtu_schema", "textbook_dem"), default="textbook_dem"),
        "textbook_chapter_max_tokens": int(getattr(settings, "textbook_chapter_max_tokens", 8000)),
    }


def _default_llm_workers() -> dict[str, Any]:
    return {"items": []}


def _default_integrations() -> dict[str, Any]:
    return {
        "crossref_mailto": _as_text(getattr(settings, "crossref_mailto", None)),
        "crossref_user_agent": _as_text(getattr(settings, "crossref_user_agent", "LogicKG/1.0"), default="LogicKG/1.0"),
    }


def _default_community() -> dict[str, Any]:
    return {
        "global_community_version": _as_text(getattr(settings, "global_community_version", "v1"), default="v1"),
        "global_community_max_nodes": int(
            getattr(settings, "global_community_max_nodes", _COMMUNITY_INT_LIMITS["global_community_max_nodes"][0])
        ),
        "global_community_max_edges": int(
            getattr(settings, "global_community_max_edges", _COMMUNITY_INT_LIMITS["global_community_max_edges"][0])
        ),
        "global_community_top_keywords": int(
            getattr(settings, "global_community_top_keywords", _COMMUNITY_INT_LIMITS["global_community_top_keywords"][0])
        ),
        "global_community_tree_comm_embedding_model": _as_text(
            getattr(settings, "global_community_tree_comm_embedding_model", "all-MiniLM-L6-v2"),
            default="all-MiniLM-L6-v2",
        ),
        "global_community_tree_comm_struct_weight": float(
            getattr(
                settings,
                "global_community_tree_comm_struct_weight",
                _COMMUNITY_FLOAT_LIMITS["global_community_tree_comm_struct_weight"][0],
            )
        ),
    }


def _normalize_choice(value: Any, *, default: str, choices: set[str]) -> str:
    candidate = _as_text(value, default=default).lower()
    if candidate not in choices:
        return default
    return candidate


def normalize_similarity_config(raw: dict[str, Any] | None, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(raw or {})
    s = dict(base or _default_similarity())
    method = str(payload.get("group_clustering_method", s.get("group_clustering_method", "hybrid")) or "").strip().lower()
    if method not in _SIMILARITY_METHODS:
        method = str(s.get("group_clustering_method", "hybrid") or "hybrid").strip().lower()
        if method not in _SIMILARITY_METHODS:
            method = "hybrid"
    s["group_clustering_method"] = method
    s["group_clustering_threshold"] = _clamp_float(
        payload.get("group_clustering_threshold", s.get("group_clustering_threshold")),
        default=float(s.get("group_clustering_threshold", 0.85)),
        lo=0.0,
        hi=1.0,
    )
    return s


def normalize_runtime_config(raw: dict[str, Any] | None, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(raw or {})
    current = dict(base or _default_runtime())
    out: dict[str, Any] = {}
    for key, (default, lo, hi) in _RUNTIME_LIMITS.items():
        out[key] = _clamp_int(payload.get(key, current.get(key, default)), default=default, lo=lo, hi=hi)
    for key, (default, lo, hi) in _RUNTIME_FLOAT_LIMITS.items():
        out[key] = _clamp_float(payload.get(key, current.get(key, default)), default=default, lo=lo, hi=hi)
    for key in _RUNTIME_BOOL_FIELDS:
        out[key] = _as_bool(payload.get(key, current.get(key, False)), default=bool(current.get(key, False)))
    return out


def normalize_providers_config(raw: dict[str, Any] | None, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(raw or {})
    current = dict(base or _default_providers())
    out = dict(current)
    out["llm_provider"] = _normalize_choice(
        payload.get("llm_provider", current.get("llm_provider", "deepseek")),
        default=str(current.get("llm_provider", "deepseek") or "deepseek"),
        choices=_PROVIDER_CHOICES,
    )
    out["embedding_provider"] = _normalize_choice(
        payload.get("embedding_provider", current.get("embedding_provider", "")),
        default=str(current.get("embedding_provider", "") or ""),
        choices=_EMBEDDING_PROVIDER_CHOICES,
    )
    for key in _PROVIDERS_FIELDS:
        if key in {"llm_provider", "embedding_provider"}:
            continue
        out[key] = _as_text(payload.get(key, current.get(key, "")))
    return out


def _worker_default_id(index: int) -> str:
    return f"worker-{index + 1}"


def normalize_llm_workers_config(raw: dict[str, Any] | None, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(raw or {})
    current = dict(base or _default_llm_workers())
    raw_items = payload.get("items", current.get("items", []))
    if not isinstance(raw_items, list):
        raw_items = []

    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, entry in enumerate(raw_items):
        row = dict(entry) if isinstance(entry, dict) else {}
        worker_id = _as_text(row.get("id"), default=_worker_default_id(index)) or _worker_default_id(index)
        if worker_id in seen_ids:
            suffix = 2
            candidate = f"{worker_id}-{suffix}"
            while candidate in seen_ids:
                suffix += 1
                candidate = f"{worker_id}-{suffix}"
            worker_id = candidate
        seen_ids.add(worker_id)
        items.append(
            {
                "id": worker_id,
                "label": _as_text(row.get("label"), default=f"LLM Worker {index + 1}") or f"LLM Worker {index + 1}",
                "base_url": _as_text(row.get("base_url")),
                "api_key": _as_text(row.get("api_key")),
                "model": _as_text(row.get("model")),
                "max_concurrent": _clamp_int(
                    row.get("max_concurrent", _LLM_WORKER_INT_LIMITS["max_concurrent"][0]),
                    default=_LLM_WORKER_INT_LIMITS["max_concurrent"][0],
                    lo=_LLM_WORKER_INT_LIMITS["max_concurrent"][1],
                    hi=_LLM_WORKER_INT_LIMITS["max_concurrent"][2],
                ),
                "enabled": _as_bool(row.get("enabled", True), default=True),
            }
        )

    return {"items": items}


def _is_routable_llm_worker(row: dict[str, Any]) -> bool:
    return bool(
        _as_bool(row.get("enabled", True), default=True)
        and _as_text(row.get("id"))
        and _as_text(row.get("base_url"))
        and _as_text(row.get("api_key"))
    )


def _estimate_llm_requests_per_paper(runtime: dict[str, Any]) -> int:
    chunk_claim_default, chunk_claim_lo, chunk_claim_hi = _RUNTIME_LIMITS["phase1_chunk_claim_max_workers"]
    grounding_default, grounding_lo, grounding_hi = _RUNTIME_LIMITS["phase1_grounding_max_workers"]
    conflict_default, conflict_lo, conflict_hi = _RUNTIME_LIMITS["phase2_conflict_max_workers"]
    chunk_claim = _clamp_int(
        runtime.get("phase1_chunk_claim_max_workers", chunk_claim_default),
        default=chunk_claim_default,
        lo=chunk_claim_lo,
        hi=chunk_claim_hi,
    )
    grounding = _clamp_int(
        runtime.get("phase1_grounding_max_workers", grounding_default),
        default=grounding_default,
        lo=grounding_lo,
        hi=grounding_hi,
    )
    conflict = _clamp_int(
        runtime.get("phase2_conflict_max_workers", conflict_default),
        default=conflict_default,
        lo=conflict_lo,
        hi=conflict_hi,
    )
    return max(1, chunk_claim, grounding, conflict)


def _derive_ingest_llm_max_workers(runtime: dict[str, Any], llm_workers: dict[str, Any] | None) -> int:
    ingest_default, ingest_lo, ingest_hi = _RUNTIME_LIMITS["ingest_llm_max_workers"]
    fallback = _clamp_int(
        runtime.get("ingest_llm_max_workers", ingest_default),
        default=ingest_default,
        lo=ingest_lo,
        hi=ingest_hi,
    )
    global_default, global_lo, global_hi = _RUNTIME_LIMITS["llm_global_max_concurrent"]
    global_cap = _clamp_int(
        runtime.get("llm_global_max_concurrent", global_default),
        default=global_default,
        lo=global_lo,
        hi=global_hi,
    )
    estimated_requests_per_paper = _estimate_llm_requests_per_paper(runtime)
    global_paper_slots = max(1, global_cap // estimated_requests_per_paper)

    items = normalize_llm_workers_config(llm_workers or {}).get("items") or []
    routable_paper_slots = 0
    for row in items:
        if not isinstance(row, dict) or not _is_routable_llm_worker(row):
            continue
        worker_capacity = _clamp_int(
            row.get("max_concurrent", _LLM_WORKER_INT_LIMITS["max_concurrent"][0]),
            default=_LLM_WORKER_INT_LIMITS["max_concurrent"][0],
            lo=_LLM_WORKER_INT_LIMITS["max_concurrent"][1],
            hi=_LLM_WORKER_INT_LIMITS["max_concurrent"][2],
        )
        routable_paper_slots += max(1, (worker_capacity + estimated_requests_per_paper - 1) // estimated_requests_per_paper)

    if routable_paper_slots > 0:
        return max(ingest_lo, min(ingest_hi, global_paper_slots, routable_paper_slots))
    return max(ingest_lo, min(ingest_hi, global_paper_slots, fallback))


def normalize_infra_config(raw: dict[str, Any] | None, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(raw or {})
    current = dict(base or _default_infra())
    out = dict(current)
    for key in _INFRA_FIELDS:
        if key == "pageindex_enabled":
            out[key] = _as_bool(payload.get(key, current.get(key, False)), default=bool(current.get(key, False)))
        elif key == "textbook_chapter_max_tokens":
            out[key] = _clamp_int(payload.get(key, current.get(key, 8000)), default=8000, lo=1000, hi=64000)
        else:
            out[key] = _as_text(payload.get(key, current.get(key, "")))
    return out


def normalize_integrations_config(raw: dict[str, Any] | None, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(raw or {})
    current = dict(base or _default_integrations())
    return {
        "crossref_mailto": _as_text(payload.get("crossref_mailto", current.get("crossref_mailto", ""))),
        "crossref_user_agent": _as_text(
            payload.get("crossref_user_agent", current.get("crossref_user_agent", "LogicKG/1.0")),
            default="LogicKG/1.0",
        ) or "LogicKG/1.0",
    }


def normalize_community_config(raw: dict[str, Any] | None, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(raw or {})
    current = dict(base or _default_community())
    out = dict(current)
    out["global_community_version"] = _as_text(
        payload.get("global_community_version", current.get("global_community_version", "v1")),
        default="v1",
    ) or "v1"
    out["global_community_tree_comm_embedding_model"] = _as_text(
        payload.get(
            "global_community_tree_comm_embedding_model",
            current.get("global_community_tree_comm_embedding_model", "all-MiniLM-L6-v2"),
        ),
        default="all-MiniLM-L6-v2",
    ) or "all-MiniLM-L6-v2"
    for key, (default, lo, hi) in _COMMUNITY_INT_LIMITS.items():
        out[key] = _clamp_int(payload.get(key, current.get(key, default)), default=default, lo=lo, hi=hi)
    for key, (default, lo, hi) in _COMMUNITY_FLOAT_LIMITS.items():
        out[key] = _clamp_float(payload.get(key, current.get(key, default)), default=default, lo=lo, hi=hi)
    return out


def default_profile() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": _now_iso(),
        "modules": {
            "similarity": normalize_similarity_config({}),
            "runtime": normalize_runtime_config({}),
            "providers": normalize_providers_config({}),
            "llm_workers": normalize_llm_workers_config({}),
            "infra": normalize_infra_config({}),
            "integrations": normalize_integrations_config({}),
            "community": normalize_community_config({}),
        },
    }


def normalize_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = default_profile()
    payload = dict(raw or {})
    modules = payload.get("modules") if isinstance(payload.get("modules"), dict) else {}
    modules_dict = modules if isinstance(modules, dict) else {}
    similarity = normalize_similarity_config(
        modules_dict.get("similarity") if isinstance(modules_dict.get("similarity"), dict) else {},
        base=base["modules"]["similarity"],
    )
    runtime = normalize_runtime_config(
        modules_dict.get("runtime") if isinstance(modules_dict.get("runtime"), dict) else {},
        base=base["modules"]["runtime"],
    )
    providers = normalize_providers_config(
        modules_dict.get("providers") if isinstance(modules_dict.get("providers"), dict) else {},
        base=base["modules"]["providers"],
    )
    llm_workers = normalize_llm_workers_config(
        modules_dict.get("llm_workers") if isinstance(modules_dict.get("llm_workers"), dict) else {},
        base=base["modules"]["llm_workers"],
    )
    infra = normalize_infra_config(
        modules_dict.get("infra") if isinstance(modules_dict.get("infra"), dict) else {},
        base=base["modules"]["infra"],
    )
    integrations = normalize_integrations_config(
        modules_dict.get("integrations") if isinstance(modules_dict.get("integrations"), dict) else {},
        base=base["modules"]["integrations"],
    )
    community = normalize_community_config(
        modules_dict.get("community") if isinstance(modules_dict.get("community"), dict) else {},
        base=base["modules"]["community"],
    )
    runtime["ingest_llm_max_workers"] = _derive_ingest_llm_max_workers(runtime, llm_workers)
    version = _clamp_int(payload.get("version", 1), default=1, lo=1, hi=9999)
    updated_at = str(payload.get("updated_at") or "").strip() or _now_iso()
    return {
        "version": version,
        "updated_at": updated_at,
        "modules": {
            "similarity": similarity,
            "runtime": runtime,
            "providers": providers,
            "llm_workers": llm_workers,
            "infra": infra,
            "integrations": integrations,
            "community": community,
        },
    }


def _env_file_layers() -> dict[str, str]:
    merged: dict[str, str] = {}
    if _CONFIG_PATH_OVERRIDE is None:
        root = _backend_root().parent
        backend = _backend_root()
        for path in (root / ".env", backend / ".env"):
            if not path.exists():
                continue
            for key, value in dotenv_values(path).items():
                if key is None or value is None:
                    continue
                merged[str(key)] = str(value)
    for key, value in os.environ.items():
        merged[str(key)] = str(value)
    return merged


def _env_override_for(field_name: str) -> tuple[bool, str | None]:
    env_values = _env_file_layers()
    for env_key in _FIELD_ENV_KEYS.get(field_name, ()):
        if env_key in env_values:
            return True, env_values.get(env_key)
    return False, None


def _coerce_field(field_name: str, raw_value: Any, default: Any) -> Any:
    if field_name == "group_clustering_method":
        return _normalize_choice(raw_value, default=str(default or "hybrid"), choices=_SIMILARITY_METHODS)
    if field_name == "llm_provider":
        return _normalize_choice(raw_value, default=str(default or "deepseek"), choices=_PROVIDER_CHOICES)
    if field_name == "embedding_provider":
        return _normalize_choice(raw_value, default=str(default or ""), choices=_EMBEDDING_PROVIDER_CHOICES)
    if field_name in _RUNTIME_LIMITS:
        lo, hi = _RUNTIME_LIMITS[field_name][1], _RUNTIME_LIMITS[field_name][2]
        return _clamp_int(raw_value, default=int(default), lo=lo, hi=hi)
    if field_name in _RUNTIME_FLOAT_LIMITS:
        lo, hi = _RUNTIME_FLOAT_LIMITS[field_name][1], _RUNTIME_FLOAT_LIMITS[field_name][2]
        return _clamp_float(raw_value, default=float(default), lo=lo, hi=hi)
    if field_name in _COMMUNITY_INT_LIMITS:
        lo, hi = _COMMUNITY_INT_LIMITS[field_name][1], _COMMUNITY_INT_LIMITS[field_name][2]
        return _clamp_int(raw_value, default=int(default), lo=lo, hi=hi)
    if field_name in _COMMUNITY_FLOAT_LIMITS:
        lo, hi = _COMMUNITY_FLOAT_LIMITS[field_name][1], _COMMUNITY_FLOAT_LIMITS[field_name][2]
        return _clamp_float(raw_value, default=float(default), lo=lo, hi=hi)
    if field_name in _RUNTIME_BOOL_FIELDS or field_name == "pageindex_enabled":
        return _as_bool(raw_value, default=bool(default))
    if field_name == "textbook_chapter_max_tokens":
        return _clamp_int(raw_value, default=int(default), lo=1000, hi=64000)
    if field_name == "group_clustering_threshold":
        return _clamp_float(raw_value, default=float(default), lo=0.0, hi=1.0)
    return _as_text(raw_value, default=_as_text(default))


def _effective_module_values(module_id: str, base: dict[str, Any]) -> dict[str, Any]:
    current = dict(base)
    for key, value in list(current.items()):
        has_env, env_value = _env_override_for(key)
        if not has_env:
            continue
        current[key] = _coerce_field(key, env_value, value)
    return current


def load_profile() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return default_profile()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return normalize_profile(raw if isinstance(raw, dict) else {})


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_profile(profile)
    normalized["updated_at"] = _now_iso()
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return normalized


def apply_profile_to_settings(profile: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = normalize_profile(profile or load_profile())
    modules = normalized.get("modules") if isinstance(normalized.get("modules"), dict) else {}
    effective = {
        "similarity": merge_similarity_config({}),
        "runtime": merge_runtime_config({}),
        "providers": merge_providers_config({}),
        "llm_workers": merge_llm_workers_config({}),
        "infra": merge_infra_config({}),
        "integrations": merge_integrations_config({}),
        "community": merge_community_config({}),
    }
    if isinstance(modules.get("similarity"), dict):
        for key, value in effective["similarity"].items():
            settings.__setattr__(key, value)
    if isinstance(modules.get("runtime"), dict):
        for key, value in effective["runtime"].items():
            settings.__setattr__(key, value)
    if isinstance(modules.get("providers"), dict):
        for key, value in effective["providers"].items():
            settings.__setattr__(key, None if key.endswith("_api_key") and value == "" else value)
    if isinstance(modules.get("infra"), dict):
        for key, value in effective["infra"].items():
            settings.__setattr__(key, value)
    if isinstance(modules.get("integrations"), dict):
        for key, value in effective["integrations"].items():
            if key == "crossref_mailto":
                settings.__setattr__(key, value or None)
            else:
                settings.__setattr__(key, value)
    if isinstance(modules.get("community"), dict):
        for key, value in effective["community"].items():
            settings.__setattr__(key, value)
    return effective


def remove_legacy_modules(module_ids: list[str] | tuple[str, ...] | set[str]) -> dict[str, Any]:
    normalized_ids = sorted({str(item or '').strip() for item in module_ids if str(item or '').strip()})
    path = _config_path()
    raw: dict[str, Any]
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            raw = dict(payload) if isinstance(payload, dict) else {}
        except Exception:
            raw = {}
    else:
        raw = {}

    modules = raw.get('modules')
    modules_dict = dict(modules) if isinstance(modules, dict) else {}
    removed_modules = [module_id for module_id in normalized_ids if module_id in modules_dict]
    for module_id in normalized_ids:
        modules_dict.pop(module_id, None)

    raw['version'] = _clamp_int(raw.get('version', 1), default=1, lo=1, hi=9999)
    raw['updated_at'] = _now_iso()
    raw['modules'] = modules_dict

    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)
    return {
        'status': 'ok',
        'removed_modules': removed_modules,
        'path': str(path),
    }


def merge_similarity_config(overrides: dict[str, Any] | None) -> dict[str, Any]:
    profile = load_profile()
    base = dict((profile.get("modules") or {}).get("similarity") or {})
    normalized = normalize_similarity_config(overrides or {}, base=base)
    return _effective_module_values("similarity", normalized)


def merge_runtime_config(overrides: dict[str, Any] | None) -> dict[str, Any]:
    profile = load_profile()
    modules = profile.get("modules") if isinstance(profile.get("modules"), dict) else {}
    base = dict(modules.get("runtime") or {})
    normalized = normalize_runtime_config(overrides or {}, base=base)
    effective = _effective_module_values("runtime", normalized)
    has_ingest_env, _ = _env_override_for("ingest_llm_max_workers")
    if has_ingest_env:
        return effective
    llm_workers = modules.get("llm_workers") if isinstance(modules.get("llm_workers"), dict) else {}
    effective["ingest_llm_max_workers"] = _derive_ingest_llm_max_workers(effective, llm_workers)
    return effective


def merge_providers_config(overrides: dict[str, Any] | None) -> dict[str, Any]:
    profile = load_profile()
    base = dict((profile.get("modules") or {}).get("providers") or {})
    normalized = normalize_providers_config(overrides or {}, base=base)
    return _effective_module_values("providers", normalized)


def merge_infra_config(overrides: dict[str, Any] | None) -> dict[str, Any]:
    profile = load_profile()
    base = dict((profile.get("modules") or {}).get("infra") or {})
    normalized = normalize_infra_config(overrides or {}, base=base)
    return _effective_module_values("infra", normalized)


def merge_llm_workers_config(overrides: dict[str, Any] | None) -> dict[str, Any]:
    profile = load_profile()
    base = dict((profile.get("modules") or {}).get("llm_workers") or {})
    return normalize_llm_workers_config(overrides or {}, base=base)


def merge_integrations_config(overrides: dict[str, Any] | None) -> dict[str, Any]:
    profile = load_profile()
    base = dict((profile.get("modules") or {}).get("integrations") or {})
    normalized = normalize_integrations_config(overrides or {}, base=base)
    return _effective_module_values("integrations", normalized)


def merge_community_config(overrides: dict[str, Any] | None) -> dict[str, Any]:
    profile = load_profile()
    base = dict((profile.get("modules") or {}).get("community") or {})
    normalized = normalize_community_config(overrides or {}, base=base)
    return _effective_module_values("community", normalized)
