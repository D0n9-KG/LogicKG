from __future__ import annotations

import json
import random
import threading
from pathlib import Path
from typing import Any

from app.settings import settings


_PROMPT_VARIANTS = ("base", "optimized")
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"scopes": {}, "meta": {"version": "rl_bandit_v1"}}
_LOADED = False


def _policy_path() -> Path:
    configured = str(getattr(settings, "discovery_prompt_policy_path", "storage/discovery/prompt_policy_bandit.json") or "").strip()
    p = Path(configured)
    if p.is_absolute():
        return p
    return Path(__file__).resolve().parents[2] / p


def _scope_key(domain: str, gap_type: str) -> str:
    d = str(domain or "default").strip().lower() or "default"
    g = str(gap_type or "seed").strip().lower() or "seed"
    return f"{d}::{g}"


def _empty_scope() -> dict[str, Any]:
    return {
        "arms": {
            name: {
                "n": 0,
                "value": 0.0,
                "total_reward": 0.0,
                "last_source": "",
            }
            for name in _PROMPT_VARIANTS
        }
    }


def _load_if_needed() -> None:
    global _LOADED, _STATE
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        path = _policy_path()
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                if isinstance(payload, dict):
                    _STATE = payload
            except Exception:
                _STATE = {"scopes": {}, "meta": {"version": "rl_bandit_v1"}}
        _LOADED = True


def _save_state() -> None:
    path = _policy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_STATE, ensure_ascii=False, indent=2), encoding="utf-8")


def _clamp01(v: float) -> float:
    if v <= 0.0:
        return 0.0
    if v >= 1.0:
        return 1.0
    return float(v)


def choose_prompt_variants(
    *,
    domain: str,
    gap_type: str,
    top_k: int = 2,
    method: str = "rl_bandit",
) -> list[str]:
    """Choose prompt variants for generation.

    method:
    - rl_bandit: epsilon-greedy multi-armed bandit with cold-start exploration
    - heuristic: deterministic base-first fallback
    """
    k = max(1, min(4, int(top_k)))
    normalized_method = str(method or "rl_bandit").strip().lower()
    if normalized_method != "rl_bandit":
        ordered = list(_PROMPT_VARIANTS)
        return ordered[:k]

    _load_if_needed()
    key = _scope_key(domain, gap_type)
    with _LOCK:
        scopes = _STATE.setdefault("scopes", {})
        scope = scopes.setdefault(key, _empty_scope())
        arms: dict[str, dict[str, Any]] = scope.setdefault("arms", {})
        for name in _PROMPT_VARIANTS:
            arms.setdefault(
                name,
                {"n": 0, "value": 0.0, "total_reward": 0.0, "last_source": ""},
            )

        cold = [name for name in _PROMPT_VARIANTS if int(arms.get(name, {}).get("n", 0)) <= 0]
        if cold:
            cursor = int(scope.get("cold_cursor", 0))
            first = cold[cursor % len(cold)]
            scope["cold_cursor"] = cursor + 1
            tail = [x for x in _PROMPT_VARIANTS if x != first]
            return [first, *tail][:k]

        total_trials = sum(max(0, int(arms.get(name, {}).get("n", 0))) for name in _PROMPT_VARIANTS)
        epsilon = max(0.05, 0.25 * (0.985 ** max(0, total_trials)))

        if random.random() < epsilon:
            first = random.choice(list(_PROMPT_VARIANTS))
        else:
            first = max(
                _PROMPT_VARIANTS,
                key=lambda name: (
                    float(arms.get(name, {}).get("value", 0.0)),
                    -int(arms.get(name, {}).get("n", 0)),
                    name,
                ),
            )

        remaining = [x for x in _PROMPT_VARIANTS if x != first]
        remaining.sort(
            key=lambda name: (
                float(arms.get(name, {}).get("value", 0.0)),
                -int(arms.get(name, {}).get("n", 0)),
                name,
            ),
            reverse=True,
        )
        return [first, *remaining][:k]


def update_prompt_policy_reward(
    *,
    domain: str,
    gap_type: str,
    prompt_variant: str,
    reward: float,
    source: str = "batch",
) -> dict[str, Any]:
    _load_if_needed()
    variant = str(prompt_variant or "").strip().lower()
    if variant not in _PROMPT_VARIANTS:
        return {"updated": False, "reason": "unknown_variant"}
    key = _scope_key(domain, gap_type)
    r = _clamp01(float(reward or 0.0))
    with _LOCK:
        scopes = _STATE.setdefault("scopes", {})
        scope = scopes.setdefault(key, _empty_scope())
        arms = scope.setdefault("arms", {})
        arm = arms.setdefault(
            variant,
            {"n": 0, "value": 0.0, "total_reward": 0.0, "last_source": ""},
        )
        n_prev = max(0, int(arm.get("n", 0)))
        v_prev = float(arm.get("value", 0.0))
        n_new = n_prev + 1
        v_new = v_prev + (r - v_prev) / float(n_new)
        arm["n"] = n_new
        arm["value"] = float(round(v_new, 6))
        arm["total_reward"] = float(round(float(arm.get("total_reward", 0.0)) + r, 6))
        arm["last_source"] = str(source or "batch")
        _save_state()
        return {
            "updated": True,
            "scope": key,
            "variant": variant,
            "n": n_new,
            "value": arm["value"],
        }


def _candidate_reward(row: dict[str, Any]) -> float:
    quality = _clamp01(float(row.get("quality_score") or 0.0))
    optimization = _clamp01(float(row.get("optimization_score") or 0.0))
    support = _clamp01(float(row.get("support_coverage") or 0.0))
    status = str(row.get("status") or "").strip().lower()
    status_bonus = 0.5
    if status == "accepted":
        status_bonus = 1.0
    elif status == "ranked":
        status_bonus = 0.75
    elif status == "needs_more_evidence":
        status_bonus = 0.35
    elif status == "rejected":
        status_bonus = 0.0
    reward = 0.55 * quality + 0.20 * optimization + 0.15 * support + 0.10 * status_bonus
    return _clamp01(reward)


def update_policy_from_candidates(*, domain: str, candidates: list[dict], source: str = "batch") -> int:
    updated = 0
    for row in candidates or []:
        variant = str(row.get("prompt_variant") or "").strip().lower()
        mode = str(row.get("generation_mode") or "").strip().lower()
        if not variant or variant not in _PROMPT_VARIANTS:
            continue
        if not mode.startswith("llm"):
            continue
        gap_type = str(row.get("gap_type") or "seed")
        update_prompt_policy_reward(
            domain=domain,
            gap_type=gap_type,
            prompt_variant=variant,
            reward=_candidate_reward(row),
            source=source,
        )
        updated += 1
    return updated


def feedback_label_reward(label: str) -> float:
    value = str(label or "").strip().lower()
    if value == "accepted":
        return 1.0
    if value == "rejected":
        return 0.0
    return 0.35


def reset_prompt_policy_for_tests() -> None:
    global _STATE, _LOADED
    with _LOCK:
        _STATE = {"scopes": {}, "meta": {"version": "rl_bandit_v1"}}
        _LOADED = True
