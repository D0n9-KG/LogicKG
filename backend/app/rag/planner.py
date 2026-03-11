from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_openai import ChatOpenAI

from app.rag.models import AskIntent, AskQueryPlan, RetrievalPlan
from app.settings import settings


log = logging.getLogger(__name__)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_SUPPORTED_QUERY_FIELDS = {"main_query", "paper_query", "textbook_query", "community_query"}
_SUPPORTED_RETRIEVAL_PLANS = {item.value for item in RetrievalPlan}


def _normalize_query_plan_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    normalized = dict(payload)
    retrieval_plan = str(normalized.get("retrieval_plan") or "").strip()
    community_query = str(normalized.get("community_query") or "").strip()
    if not community_query:
        legacy_query = next(
            (
                str(value).strip()
                for key, value in normalized.items()
                if str(key).endswith("_query")
                and str(key) not in _SUPPORTED_QUERY_FIELDS
                and str(value).strip()
            ),
            "",
        )
        if legacy_query:
            normalized["community_query"] = legacy_query
    if retrieval_plan and retrieval_plan not in _SUPPORTED_RETRIEVAL_PLANS and normalized.get("community_query"):
        normalized["retrieval_plan"] = "community_first"
    normalized = {
        key: value
        for key, value in normalized.items()
        if key in {"intent", "retrieval_plan", "main_query", "paper_query", "textbook_query", "community_query", "confidence", "reason"}
    }
    return normalized


def fallback_query_plan(question: str) -> AskQueryPlan:
    return AskQueryPlan(
        intent=AskIntent.paper_detail,
        retrieval_plan=RetrievalPlan.paper_first_then_textbook,
        main_query=str(question or "").strip() or "question",
    )


def resolve_query_plan(question: str, payload: dict[str, Any] | None) -> AskQueryPlan:
    try:
        normalized_payload = _normalize_query_plan_payload(payload)
        if not isinstance(normalized_payload, dict):
            raise ValueError("planner payload must be a dict")
        return AskQueryPlan.model_validate(normalized_payload)
    except Exception:
        return fallback_query_plan(question)


def _extract_json_payload(content: Any) -> dict[str, Any] | None:
    text = str(content or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        match = _JSON_RE.search(text)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None


def plan_ask_query(question: str, scope: dict | None = None, locale: str | None = None) -> AskQueryPlan:
    text = str(question or "").strip()
    fallback = fallback_query_plan(text)
    api_key = settings.effective_llm_api_key()
    if not api_key:
        return fallback

    timeout_seconds = max(5, min(20, int(getattr(settings, "llm_timeout_seconds", 60) or 60) // 4 or 12))
    scope_json = json.dumps(scope or {"mode": "all"}, ensure_ascii=False, sort_keys=True)
    try:
        client = ChatOpenAI(
            api_key=api_key,
            base_url=settings.effective_llm_base_url(),
            model=settings.llm_model,
            temperature=0,
            timeout=timeout_seconds,
            max_tokens=256,
            max_retries=0,
        )
        response = client.invoke(
            [
                (
                    "system",
                    (
                        "You are a retrieval planner for a scientific QA system. "
                        "Do not answer the user question. "
                        "Return only one JSON object with keys: "
                        "intent, retrieval_plan, main_query, paper_query, textbook_query, community_query, confidence, reason. "
                        "main_query is mandatory. "
                        "Valid intents: paper_detail, foundational, hybrid_explanation, comparison. "
                        "Valid retrieval plans: paper_first_then_textbook, textbook_first_then_paper, hybrid_parallel, claim_first, community_first."
                    ),
                ),
                (
                    "user",
                    (
                        f"Locale: {locale or 'en-US'}\n"
                        f"Scope: {scope_json}\n"
                        f"Question: {text}\n"
                        "Return JSON only."
                    ),
                ),
            ]
        )
    except Exception:
        log.debug("Ask planner call failed; using fallback", exc_info=True)
        return fallback

    payload = _extract_json_payload(getattr(response, "content", ""))
    return resolve_query_plan(text, payload)
