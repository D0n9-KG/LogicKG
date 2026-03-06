from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


GapType = Literal[
    "conflict_hotspot",
    "future_work",
    "limitation",
    "gap_claim",
    "challenged_proposition",
    "seed",
]


GenerationMode = Literal["template", "llm", "llm_optimized", "llm_rl"]


class ResearchQuestionCandidate(BaseModel):
    candidate_id: str
    question: str = Field(min_length=3)
    gap_id: str | None = None
    gap_type: GapType = "seed"

    motivation: str | None = None
    novelty: str | None = None
    proposed_method: str | None = None
    difference: str | None = None
    feasibility: str | None = None
    risk_statement: str | None = None
    evaluation_metrics: list[str] = Field(default_factory=list)
    timeline: str | None = None

    source_claim_ids: list[str] = Field(default_factory=list)
    source_proposition_ids: list[str] = Field(default_factory=list)
    source_paper_ids: list[str] = Field(default_factory=list)
    inspiration_adjacent_paper_ids: list[str] = Field(default_factory=list)
    inspiration_random_paper_ids: list[str] = Field(default_factory=list)
    inspiration_community_paper_ids: list[str] = Field(default_factory=list)

    graph_context_summary: str | None = None
    rag_context_snippets: list[str] = Field(default_factory=list)

    generation_mode: GenerationMode = "template"
    prompt_variant: str | None = None
    generation_confidence: float = 0.0
    optimization_score: float = 0.0

    novelty_score: float = 0.0
    feasibility_score: float = 0.0
    relevance_score: float = 0.0
    support_coverage: float = 0.0
    challenge_coverage: float = 0.0

    support_evidence_ids: list[str] = Field(default_factory=list)
    challenge_evidence_ids: list[str] = Field(default_factory=list)
    missing_evidence_statement: str | None = None
    quality_score: float = 0.0
    status: Literal["draft", "needs_more_evidence", "ranked", "accepted", "rejected"] = "draft"

    @field_validator("support_evidence_ids", mode="after")
    @classmethod
    def _validate_support_evidence(cls, v: list[str]) -> list[str]:
        cleaned = [str(x).strip() for x in v if str(x).strip()]
        if not cleaned:
            raise ValueError("support_evidence_ids must contain at least one evidence id")
        return cleaned

    @field_validator("challenge_evidence_ids", mode="after")
    @classmethod
    def _validate_challenge_evidence(cls, v: list[str]) -> list[str]:
        return [str(x).strip() for x in v if str(x).strip()]

    @field_validator(
        "source_claim_ids",
        "source_proposition_ids",
        "source_paper_ids",
        "inspiration_adjacent_paper_ids",
        "inspiration_random_paper_ids",
        "inspiration_community_paper_ids",
        "evaluation_metrics",
        "rag_context_snippets",
        mode="after",
    )
    @classmethod
    def _dedup_str_list(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for raw in v or []:
            item = str(raw).strip()
            if not item or item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out


class FeedbackRecord(BaseModel):
    feedback_id: str
    candidate_id: str
    label: Literal["accepted", "rejected", "needs_revision"]
    note: str | None = None
    weight: float = 1.0
    created_at: str = Field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
