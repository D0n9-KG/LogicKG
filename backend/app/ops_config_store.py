from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.settings import settings


_DISCOVERY_COMMUNITY_METHODS = {"author_hop", "louvain", "hybrid"}
_DISCOVERY_PROMPT_OPT_METHODS = {"rl_bandit", "heuristic"}
_SIMILARITY_METHODS = {"agglomerative", "louvain", "hybrid"}

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


def _default_discovery() -> dict[str, Any]:
    return {
        "domain": "granular_flow",
        "dry_run": True,
        "max_gaps": 8,
        "candidates_per_gap": 2,
        "use_llm": True,
        "hop_order": 2,
        "adjacent_samples": 6,
        "random_samples": 2,
        "rag_top_k": 4,
        "prompt_optimize": True,
        "community_method": "hybrid",
        "community_samples": 4,
        "prompt_optimization_method": "rl_bandit",
    }


def _default_similarity() -> dict[str, Any]:
    return {
        "group_clustering_method": str(getattr(settings, "group_clustering_method", "hybrid") or "hybrid"),
        "group_clustering_threshold": float(getattr(settings, "group_clustering_threshold", 0.85) or 0.85),
    }


def default_profile() -> dict[str, Any]:
    return {
        "version": 1,
        "updated_at": _now_iso(),
        "modules": {
            "discovery": normalize_discovery_config({}),
            "similarity": normalize_similarity_config({}),
        },
    }


def normalize_discovery_config(raw: dict[str, Any] | None, *, base: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(raw or {})
    d = dict(base or _default_discovery())

    domain = str(payload.get("domain", d.get("domain", "granular_flow")) or "").strip()
    if not domain:
        domain = str(d.get("domain", "granular_flow"))
    d["domain"] = domain
    d["dry_run"] = _as_bool(payload.get("dry_run", d.get("dry_run")), default=bool(d.get("dry_run", True)))
    d["max_gaps"] = _clamp_int(payload.get("max_gaps", d.get("max_gaps")), default=int(d.get("max_gaps", 8)), lo=1, hi=64)
    d["candidates_per_gap"] = _clamp_int(
        payload.get("candidates_per_gap", d.get("candidates_per_gap")),
        default=int(d.get("candidates_per_gap", 2)),
        lo=1,
        hi=3,
    )
    d["use_llm"] = _as_bool(payload.get("use_llm", d.get("use_llm")), default=bool(d.get("use_llm", True)))
    d["hop_order"] = _clamp_int(payload.get("hop_order", d.get("hop_order")), default=int(d.get("hop_order", 2)), lo=1, hi=3)
    d["adjacent_samples"] = _clamp_int(
        payload.get("adjacent_samples", d.get("adjacent_samples")),
        default=int(d.get("adjacent_samples", 6)),
        lo=0,
        hi=30,
    )
    d["random_samples"] = _clamp_int(
        payload.get("random_samples", d.get("random_samples")),
        default=int(d.get("random_samples", 2)),
        lo=0,
        hi=30,
    )
    d["rag_top_k"] = _clamp_int(payload.get("rag_top_k", d.get("rag_top_k")), default=int(d.get("rag_top_k", 4)), lo=1, hi=8)
    d["prompt_optimize"] = _as_bool(
        payload.get("prompt_optimize", d.get("prompt_optimize")),
        default=bool(d.get("prompt_optimize", True)),
    )
    community_method = str(payload.get("community_method", d.get("community_method", "hybrid")) or "").strip().lower()
    if community_method not in _DISCOVERY_COMMUNITY_METHODS:
        community_method = str(d.get("community_method", "hybrid")).strip().lower()
        if community_method not in _DISCOVERY_COMMUNITY_METHODS:
            community_method = "hybrid"
    d["community_method"] = community_method
    d["community_samples"] = _clamp_int(
        payload.get("community_samples", d.get("community_samples")),
        default=int(d.get("community_samples", 4)),
        lo=0,
        hi=30,
    )
    prompt_method = str(payload.get("prompt_optimization_method", d.get("prompt_optimization_method", "rl_bandit")) or "").strip().lower()
    if prompt_method not in _DISCOVERY_PROMPT_OPT_METHODS:
        prompt_method = str(d.get("prompt_optimization_method", "rl_bandit")).strip().lower()
        if prompt_method not in _DISCOVERY_PROMPT_OPT_METHODS:
            prompt_method = "rl_bandit"
    d["prompt_optimization_method"] = prompt_method
    return d


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


def normalize_profile(raw: dict[str, Any] | None) -> dict[str, Any]:
    base = default_profile()
    payload = dict(raw or {})
    modules = payload.get("modules") if isinstance(payload.get("modules"), dict) else {}
    modules_dict = modules if isinstance(modules, dict) else {}

    discovery = normalize_discovery_config(
        modules_dict.get("discovery") if isinstance(modules_dict.get("discovery"), dict) else {},
        base=base["modules"]["discovery"],
    )
    similarity = normalize_similarity_config(
        modules_dict.get("similarity") if isinstance(modules_dict.get("similarity"), dict) else {},
        base=base["modules"]["similarity"],
    )

    version = _clamp_int(payload.get("version", 1), default=1, lo=1, hi=9999)
    updated_at = str(payload.get("updated_at") or "").strip() or _now_iso()
    return {
        "version": version,
        "updated_at": updated_at,
        "modules": {
            "discovery": discovery,
            "similarity": similarity,
        },
    }


def load_profile() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        profile = default_profile()
        save_profile(profile)
        return profile
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    profile = normalize_profile(raw if isinstance(raw, dict) else {})
    # Self-heal on malformed file.
    save_profile(profile)
    return profile


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_profile(profile)
    normalized["updated_at"] = _now_iso()
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return normalized


def merge_discovery_config(overrides: dict[str, Any] | None) -> dict[str, Any]:
    profile = load_profile()
    base = dict((profile.get("modules") or {}).get("discovery") or {})
    return normalize_discovery_config(overrides or {}, base=base)


def merge_similarity_config(overrides: dict[str, Any] | None) -> dict[str, Any]:
    profile = load_profile()
    base = dict((profile.get("modules") or {}).get("similarity") or {})
    return normalize_similarity_config(overrides or {}, base=base)

