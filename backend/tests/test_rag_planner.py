"""Tests for the Ask query planner contracts."""
from __future__ import annotations

import importlib

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
