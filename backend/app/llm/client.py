from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
import time
from concurrent.futures import Executor, Future
from contextlib import contextmanager
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from app.ops_config_store import merge_llm_workers_config, merge_runtime_config
from app.settings import settings

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)


_JSON_BLOCK_RE = re.compile(r"```json\s*(?P<body>.*?)\s*```", re.DOTALL | re.IGNORECASE)
_VALID_JSON_ESCAPES = frozenset('"\\/bfnrt')

_LLM_SEMAPHORE: threading.Semaphore | None = None
_LLM_SEMAPHORE_LOCK = threading.Lock()
_WORKER_SEMAPHORES: dict[str, tuple[int, threading.Semaphore]] = {}
_WORKER_SEMAPHORE_LOCK = threading.Lock()
_BOUND_LLM_WORKER_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("bound_llm_worker_id", default=None)
_ACTIVE_LLM_PAPER_COUNT: contextvars.ContextVar[int | None] = contextvars.ContextVar("active_llm_paper_count", default=None)
_LAST_LLM_REQUEST_CONFIG: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "last_llm_request_config",
    default=None,
)
_ROUTED_WORKER_CURSOR = 0
_ROUTED_WORKER_CURSOR_LOCK = threading.Lock()


def _get_semaphore() -> threading.Semaphore:
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        with _LLM_SEMAPHORE_LOCK:
            if _LLM_SEMAPHORE is None:
                runtime = merge_runtime_config({})
                _LLM_SEMAPHORE = threading.Semaphore(
                    int(runtime.get("llm_global_max_concurrent") or settings.llm_global_max_concurrent)
                )
    return _LLM_SEMAPHORE


def _get_worker_semaphore(worker_id: str, max_concurrent: int) -> threading.Semaphore:
    with _WORKER_SEMAPHORE_LOCK:
        current = _WORKER_SEMAPHORES.get(worker_id)
        if current is None or current[0] != max_concurrent:
            current = (max_concurrent, threading.Semaphore(max_concurrent))
            _WORKER_SEMAPHORES[worker_id] = current
        return current[1]


def get_bound_llm_worker_id() -> str | None:
    return _BOUND_LLM_WORKER_ID.get()


def get_active_llm_paper_count() -> int | None:
    value = _ACTIVE_LLM_PAPER_COUNT.get()
    if value is None:
        return None
    try:
        return max(1, int(value))
    except Exception:
        return None


def get_last_llm_request_config() -> dict[str, Any] | None:
    current = _LAST_LLM_REQUEST_CONFIG.get()
    if not isinstance(current, dict):
        return None
    return dict(current)


def _llm_request_source_label(resolved: dict[str, Any] | None) -> str:
    if not isinstance(resolved, dict):
        return "worker=default source=fallback"
    worker_id = str(resolved.get("worker_id") or "").strip() or "default"
    base_url = str(resolved.get("base_url") or "").strip() or "fallback"
    model = str(resolved.get("model") or "").strip() or "unknown"
    return f"worker={worker_id} source={base_url} model={model}"


@contextmanager
def bind_llm_worker(worker_id: str | None):
    token = _BOUND_LLM_WORKER_ID.set(str(worker_id or "").strip() or None)
    try:
        yield
    finally:
        _BOUND_LLM_WORKER_ID.reset(token)


@contextmanager
def bind_active_llm_paper_count(active_papers: int | None):
    value: int | None
    if active_papers is None:
        value = None
    else:
        try:
            value = max(1, int(active_papers))
        except Exception:
            value = 1
    token = _ACTIVE_LLM_PAPER_COUNT.set(value)
    try:
        yield
    finally:
        _ACTIVE_LLM_PAPER_COUNT.reset(token)


def submit_with_current_llm_context(executor: Executor, fn: Any, /, *args: Any, **kwargs: Any) -> Future:
    ctx = contextvars.copy_context()
    return executor.submit(lambda: ctx.run(fn, *args, **kwargs))


def list_enabled_llm_workers() -> list[dict[str, Any]]:
    items = merge_llm_workers_config({}).get("items") or []
    workers: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        worker_id = str(row.get("id") or "").strip()
        base_url = str(row.get("base_url") or "").strip()
        api_key = str(row.get("api_key") or "").strip()
        if not worker_id or not base_url or not api_key or not bool(row.get("enabled", True)):
            continue
        try:
            max_concurrent = int(row.get("max_concurrent") or 1)
        except Exception:
            max_concurrent = 1
        workers.append(
            {
                "id": worker_id,
                "label": str(row.get("label") or "").strip() or worker_id,
                "base_url": base_url,
                "api_key": api_key,
                "model": str(row.get("model") or "").strip(),
                "max_concurrent": max(1, min(16, max_concurrent)),
                "enabled": True,
            }
        )
    return workers


def _resolved_config_from_worker(worker: dict[str, Any]) -> dict[str, Any]:
    return {
        "worker_id": worker["id"],
        "api_key": worker["api_key"],
        "base_url": worker["base_url"],
        "model": worker["model"] or settings.llm_model,
        "max_concurrent": worker["max_concurrent"],
    }


def _resolve_bound_worker_config(worker_id: str) -> dict[str, Any] | None:
    for worker in list_enabled_llm_workers():
        if worker["id"] != worker_id:
            continue
        return _resolved_config_from_worker(worker)
    return None


def _expand_worker_slots(workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weighted_workers: list[tuple[dict[str, Any], int]] = []
    for worker in workers:
        if not isinstance(worker, dict):
            continue
        worker_id = str(worker.get("id") or "").strip()
        if not worker_id or not bool(worker.get("enabled", True)):
            continue
        try:
            capacity = int(worker.get("max_concurrent") or 1)
        except Exception:
            capacity = 1
        weighted_workers.append((worker, max(1, min(16, capacity))))
    if not weighted_workers:
        return []
    slots: list[dict[str, Any]] = []
    max_capacity = max(capacity for _, capacity in weighted_workers)
    for level in range(max_capacity):
        for worker, capacity in weighted_workers:
            if capacity > level:
                slots.append(worker)
    return slots


def _next_worker_probe_order(workers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    slots = _expand_worker_slots(workers)
    if not slots:
        return []
    global _ROUTED_WORKER_CURSOR
    with _ROUTED_WORKER_CURSOR_LOCK:
        start = _ROUTED_WORKER_CURSOR % len(slots)
        _ROUTED_WORKER_CURSOR = (_ROUTED_WORKER_CURSOR + 1) % len(slots)
    return slots[start:] + slots[:start]


def _acquire_unbound_worker_route() -> tuple[dict[str, Any] | None, threading.Semaphore | None]:
    while True:
        workers = list_enabled_llm_workers()
        probe_order = _next_worker_probe_order(workers)
        if not probe_order:
            return None, None
        for worker in probe_order:
            worker_sem = _get_worker_semaphore(worker["id"], int(worker["max_concurrent"] or 1))
            if worker_sem.acquire(blocking=False):
                return _resolved_config_from_worker(worker), worker_sem
        time.sleep(0.01)


def resolve_llm_request_config() -> dict[str, Any]:
    worker_id = get_bound_llm_worker_id()
    if worker_id:
        resolved = _resolve_bound_worker_config(worker_id)
        if resolved is not None:
            return resolved

    return {
        "worker_id": None,
        "api_key": settings.effective_llm_api_key(),
        "base_url": settings.effective_llm_base_url(),
        "model": settings.llm_model,
        "max_concurrent": None,
    }


def recommend_llm_subtask_workers(
    *,
    configured: int,
    batch_count: int,
    hard_cap: int,
) -> int:
    try:
        configured_value = max(1, int(configured))
    except Exception:
        configured_value = 1
    try:
        batch_total = max(1, int(batch_count))
    except Exception:
        batch_total = 1
    try:
        cap_value = max(1, int(hard_cap))
    except Exception:
        cap_value = configured_value

    runtime = merge_runtime_config({})
    try:
        global_cap = max(1, int(runtime.get("llm_global_max_concurrent") or settings.llm_global_max_concurrent))
    except Exception:
        global_cap = max(1, int(settings.llm_global_max_concurrent))
    active_papers = get_active_llm_paper_count() or 1
    per_paper_budget = max(1, global_cap // max(1, active_papers))
    target = max(configured_value, min(cap_value, per_paper_budget))
    return max(1, min(batch_total, target))


def _prepare_json_candidate(text: str) -> str:
    prepared = (text or "").lstrip("\ufeff").strip()
    match = _JSON_BLOCK_RE.search(prepared)
    if match:
        prepared = match.group("body").strip()
    starts = [prepared.find(ch) for ch in ("{", "[")]
    starts = [idx for idx in starts if idx >= 0]
    if starts:
        prepared = prepared[min(starts) :].lstrip()
    return prepared


def _repair_invalid_json_escapes(text: str) -> str:
    repaired: list[str] = []
    in_string = False
    i = 0
    while i < len(text):
        ch = text[i]
        if not in_string:
            repaired.append(ch)
            if ch == '"':
                in_string = True
            i += 1
            continue
        if ch == '"':
            repaired.append(ch)
            in_string = False
            i += 1
            continue
        if ch != "\\":
            repaired.append(ch)
            i += 1
            continue
        if i + 1 >= len(text):
            repaired.append("\\\\")
            i += 1
            continue
        nxt = text[i + 1]
        if nxt in _VALID_JSON_ESCAPES:
            repaired.append("\\")
            repaired.append(nxt)
            i += 2
            continue
        if nxt == "u":
            hex_part = text[i + 2 : i + 6]
            if len(hex_part) == 4 and all(ch in "0123456789abcdefABCDEF" for ch in hex_part):
                repaired.append("\\u")
                repaired.append(hex_part)
                i += 6
                continue
        repaired.append("\\\\")
        i += 1
    return "".join(repaired)


def _extract_json_value(text: str) -> Any:
    candidate = _prepare_json_candidate(text)
    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    attempted: list[str] = []
    for raw in (candidate, _repair_invalid_json_escapes(candidate)):
        if raw in attempted:
            continue
        attempted.append(raw)
        try:
            parsed, _end = decoder.raw_decode(raw)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        return parsed
    if last_error is not None:
        raise last_error
    raise ValueError("LLM JSON payload missing")


def _extract_json(text: str) -> dict:
    parsed = _extract_json_value(text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM JSON payload is not an object")
    return parsed


def _coerce_json_payload_for_model(payload: Any, model_class: type[_T]) -> Any:
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, list):
        return payload
    model_fields = getattr(model_class, "model_fields", {}) or {}
    if len(model_fields) != 1:
        return payload
    only_field = next(iter(model_fields.keys()))
    return {only_field: payload}


def _build_llm_client(resolved: dict[str, Any]) -> Any:
    from langchain_openai import ChatOpenAI

    api_key = str(resolved.get("api_key") or "").strip()
    base_url = resolved.get("base_url")
    model = str(resolved.get("model") or settings.llm_model).strip() or settings.llm_model
    if not api_key:
        raise RuntimeError("LLM API key missing (set DEEPSEEK_API_KEY or LLM_API_KEY)")

    try:
        timeout_seconds = int(getattr(settings, "llm_timeout_seconds", 60) or 60)
    except Exception:
        timeout_seconds = 60
    timeout_seconds = max(10, min(600, timeout_seconds))
    client_retries = max(0, min(2, int(getattr(settings, "llm_client_max_retries", 0) or 0)))

    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0,
        timeout=timeout_seconds,
        max_retries=client_retries,
    )


def llm() -> Any:
    return _build_llm_client(resolve_llm_request_config())


def test_llm_worker_connection(worker: dict[str, Any]) -> dict[str, Any]:
    worker_id = str(worker.get("id") or "").strip() or "worker-test"
    base_url = str(worker.get("base_url") or "").strip()
    api_key = str(worker.get("api_key") or "").strip()
    model = str(worker.get("model") or "").strip() or settings.llm_model
    try:
        max_concurrent = int(worker.get("max_concurrent") or 1)
    except Exception:
        max_concurrent = 1
    max_concurrent = max(1, min(16, max_concurrent))

    if not base_url:
        return {"ok": False, "error": "Worker base_url missing"}
    if not api_key:
        return {"ok": False, "error": "Worker api_key missing"}

    resolved = {
        "worker_id": worker_id,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "max_concurrent": max_concurrent,
    }
    sem = _get_semaphore()
    worker_sem = _get_worker_semaphore(worker_id, max_concurrent)
    sem.acquire()
    worker_sem.acquire()
    try:
        resp = _build_llm_client(resolved).invoke(
            [
                ("system", "You are a connectivity probe. Reply with OK only."),
                ("user", "Reply with OK."),
            ]
        )
        text = str(resp.content or "").strip()
        return {"ok": True, "error": None, "response": text}
    except Exception as exc:
        logger.warning("LLM worker connectivity test failed for %s: %s", worker_id, exc)
        return {"ok": False, "error": str(exc).strip() or exc.__class__.__name__}
    finally:
        worker_sem.release()
        sem.release()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.8, min=0.8, max=4.0))
def _call_text_with_retry(system: str, user: str, resolved: dict[str, Any]) -> str:
    resp = _build_llm_client(resolved).invoke([("system", system), ("user", user)])
    return str(resp.content or "")


def call_text(system: str, user: str, *, use_retry: bool = True) -> str:
    sem = _get_semaphore()
    worker_sem: threading.Semaphore | None = None
    sem.acquire()
    try:
        resolved = resolve_llm_request_config()
        worker_id = str(resolved.get("worker_id") or "").strip()
        if worker_id:
            worker_sem = _get_worker_semaphore(worker_id, int(resolved.get("max_concurrent") or 1))
            worker_sem.acquire()
        else:
            resolved_candidate, routed_sem = _acquire_unbound_worker_route()
            if resolved_candidate is not None:
                resolved = resolved_candidate
                worker_sem = routed_sem
        _LAST_LLM_REQUEST_CONFIG.set(dict(resolved))
        if use_retry:
            return _call_text_with_retry(system, user, resolved)
        resp = _build_llm_client(resolved).invoke([("system", system), ("user", user)])
        return str(resp.content or "")
    finally:
        if worker_sem is not None:
            worker_sem.release()
        sem.release()


def call_json(system: str, user: str, *, use_retry: bool = True) -> dict:
    raw = call_text(system, user, use_retry=use_retry)
    return _extract_json(raw)


def call_validated_json(
    system: str,
    user: str,
    model_class: type[_T],
    *,
    max_retries: int = 1,
    use_retry: bool = True,
) -> _T:
    last_error: ValidationError | None = None
    for attempt in range(1 + max_retries):
        try:
            if attempt == 0:
                raw_payload = _coerce_json_payload_for_model(_extract_json_value(call_text(system, user, use_retry=use_retry)), model_class)
            else:
                error_hint = (
                    f"\n\n[VALIDATION ERROR from previous attempt - please fix]\n"
                    f"{last_error}\n"
                    f"Return corrected JSON."
                )
                raw_payload = _coerce_json_payload_for_model(
                    _extract_json_value(call_text(system + error_hint, user, use_retry=use_retry)),
                    model_class,
                )
            return model_class.model_validate(raw_payload)
        except ValidationError as exc:
            last_error = exc
            resolved = get_last_llm_request_config()
            logger.warning(
                "LLM output validation failed (attempt %d/%d, model=%s, %s): %s",
                attempt + 1,
                1 + max_retries,
                model_class.__name__,
                _llm_request_source_label(resolved),
                exc,
            )
        except Exception as exc:
            resolved = get_last_llm_request_config()
            logger.warning(
                "LLM call/parse failed (attempt %d/%d, %s): %s",
                attempt + 1,
                1 + max_retries,
                _llm_request_source_label(resolved),
                exc,
            )
            if attempt >= max_retries:
                raise
    raise last_error  # type: ignore[misc]
