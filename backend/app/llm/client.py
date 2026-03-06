from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from app.settings import settings

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)


_JSON_BLOCK_RE = re.compile(r"```json\s*(?P<body>.*?)\s*```", re.DOTALL | re.IGNORECASE)

# ── Global LLM concurrency limiter (Phase 3) ──
_LLM_SEMAPHORE: threading.Semaphore | None = None
_LLM_SEMAPHORE_LOCK = threading.Lock()


def _get_semaphore() -> threading.Semaphore:
    """Lazy-init global LLM concurrency semaphore (thread-safe)."""
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        with _LLM_SEMAPHORE_LOCK:
            if _LLM_SEMAPHORE is None:
                _LLM_SEMAPHORE = threading.Semaphore(settings.llm_global_max_concurrent)
    return _LLM_SEMAPHORE


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    m = _JSON_BLOCK_RE.search(text)
    if m:
        text = m.group("body").strip()
    # Try to locate first { ... } if extra text exists
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


def llm() -> Any:
    from langchain_openai import ChatOpenAI

    api_key = settings.effective_llm_api_key()
    base_url = settings.effective_llm_base_url()
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
        model=settings.llm_model,
        temperature=0,
        timeout=timeout_seconds,
        max_retries=client_retries,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.8, min=0.8, max=4.0))
def _call_text_with_retry(system: str, user: str) -> str:
    """Call LLM with retry logic and return raw text response."""
    resp = llm().invoke([("system", system), ("user", user)])
    return str(resp.content or "")


def call_text(system: str, user: str, *, use_retry: bool = True) -> str:
    """
    Call LLM and return raw text response.

    Acquires the global concurrency semaphore before invoking the LLM,
    ensuring total in-flight LLM calls never exceed llm_global_max_concurrent.

    Args:
        system: System prompt
        user: User prompt
        use_retry: Whether to use retry logic (default: True)

    Returns:
        Raw text response from LLM
    """
    sem = _get_semaphore()
    sem.acquire()
    try:
        if use_retry:
            return _call_text_with_retry(system, user)
        resp = llm().invoke([("system", system), ("user", user)])
        return str(resp.content or "")
    finally:
        sem.release()


def call_json(system: str, user: str, *, use_retry: bool = True) -> dict:
    """
    Call LLM and parse JSON response.

    Args:
        system: System prompt
        user: User prompt
        use_retry: Whether to use retry logic (default: True)

    Returns:
        Parsed JSON dict

    Raises:
        JSONDecodeError: If response is not valid JSON
    """
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
    """
    Call LLM, parse JSON, and validate against a Pydantic model.

    On validation failure, retries once with the error message appended
    to the system prompt to guide the LLM toward correct output.

    Args:
        system: System prompt
        user: User prompt
        model_class: Pydantic BaseModel subclass to validate against
        max_retries: Number of validation retries (default: 1)
        use_retry: Whether to use LLM-level retry logic

    Returns:
        Validated Pydantic model instance

    Raises:
        ValidationError: If validation fails after all retries
    """
    last_error: ValidationError | None = None
    for attempt in range(1 + max_retries):
        try:
            if attempt == 0:
                raw_dict = call_json(system, user, use_retry=use_retry)
            else:
                # Append validation error to system prompt for correction
                error_hint = (
                    f"\n\n[VALIDATION ERROR from previous attempt — please fix]\n"
                    f"{last_error}\n"
                    f"Return corrected JSON."
                )
                raw_dict = call_json(system + error_hint, user, use_retry=use_retry)
            return model_class.model_validate(raw_dict)
        except ValidationError as exc:
            last_error = exc
            logger.warning(
                "LLM output validation failed (attempt %d/%d, model=%s): %s",
                attempt + 1, 1 + max_retries, model_class.__name__, exc,
            )
        except Exception as exc:
            # JSON parse failure etc. — wrap as validation error context
            logger.warning(
                "LLM call/parse failed (attempt %d/%d): %s",
                attempt + 1, 1 + max_retries, exc,
            )
            if attempt >= max_retries:
                raise
    # All retries exhausted — raise last validation error
    raise last_error  # type: ignore[misc]

