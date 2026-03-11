"""Tests for the Ask query planner contracts."""
from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError


def _planner_module():
    return importlib.import_module("app.rag.planner")


def test_query_plan_rejects_invalid_enum_values() -> None:
    planner = _planner_module()

    with pytest.raises(ValidationError):
        planner.AskQueryPlan.model_validate(
            {
                "intent": "unknown",
                "retrieval_plan": "not_a_plan",
                "main_query": "finite element method assumptions",
            }
        )


def test_resolve_query_plan_falls_back_when_main_query_missing() -> None:
    planner = _planner_module()

    plan = planner.resolve_query_plan(
        "finite element method assumptions",
        {
            "intent": "foundational",
            "retrieval_plan": "textbook_first_then_paper",
            "paper_query": "finite element method assumptions in this paper",
        },
    )

    assert plan.intent == planner.AskIntent.paper_detail
    assert plan.retrieval_plan == planner.RetrievalPlan.paper_first_then_textbook
    assert plan.main_query == "finite element method assumptions"


def test_fallback_query_plan_is_deterministic() -> None:
    planner = _planner_module()

    first = planner.fallback_query_plan("What assumptions does FEM make?")
    second = planner.fallback_query_plan("What assumptions does FEM make?")

    assert first.model_dump() == second.model_dump()
    assert first.intent == planner.AskIntent.paper_detail
    assert first.retrieval_plan == planner.RetrievalPlan.paper_first_then_textbook
    assert first.main_query == "What assumptions does FEM make?"


def test_resolve_query_plan_maps_legacy_proposition_fields_to_community_contract() -> None:
    planner = _planner_module()

    plan = planner.resolve_query_plan(
        "finite element method assumptions",
        {
            "intent": "foundational",
            "retrieval_plan": "proposition_first",
            "main_query": "finite element method assumptions",
            "proposition_query": "finite element method assumptions cluster",
        },
    )

    dumped = plan.model_dump(exclude_none=True)
    assert plan.retrieval_plan == planner.RetrievalPlan.community_first
    assert plan.community_query == "finite element method assumptions cluster"
    assert "proposition_query" not in dumped
    assert "proposition_first" not in {item.value for item in planner.RetrievalPlan}


def test_plan_ask_query_prompt_omits_proposition_runtime_terms(monkeypatch) -> None:
    planner = _planner_module()
    captured: dict[str, object] = {}

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured["init"] = kwargs

        def invoke(self, messages):
            captured["messages"] = messages
            return SimpleNamespace(
                content='{"intent":"foundational","retrieval_plan":"community_first","main_query":"finite element method assumptions"}'
            )

    monkeypatch.setattr(planner, "ChatOpenAI", _FakeChatOpenAI)
    monkeypatch.setattr(
        planner,
        "settings",
        SimpleNamespace(
            effective_llm_api_key=lambda: "fake-key",
            effective_llm_base_url=lambda: "https://example.invalid/v1",
            llm_model="fake-model",
            llm_timeout_seconds=60,
        ),
    )

    plan = planner.plan_ask_query("What are the assumptions of FEM?", scope={"mode": "all"}, locale="en-US")
    system_prompt = str(captured["messages"][0][1])

    assert plan.retrieval_plan == planner.RetrievalPlan.community_first
    assert "community_query" in system_prompt
    assert "community_first" in system_prompt
    assert "proposition_query" not in system_prompt
    assert "proposition_first" not in system_prompt
