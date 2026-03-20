from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LogicStepTrace(BaseModel):
    logic_step_id: str
    step_type: str
    summary: str = ''
    confidence: float | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    operation_or_method: list[str] = Field(default_factory=list)
    research_object: list[str] = Field(default_factory=list)
    observed_variable: list[str] = Field(default_factory=list)
    metric: list[str] = Field(default_factory=list)
    condition_context: list[str] = Field(default_factory=list)
    resource_mentions: list[str] = Field(default_factory=list)


class ClaimTrace(BaseModel):
    claim_id: str | None = None
    claim_key: str
    text: str
    step_type: str | None = None
    confidence: float | None = None
    kinds: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    targets: list[dict[str, Any]] = Field(default_factory=list)
    comparison_target: list[str] = Field(default_factory=list)
    effect_direction: str | None = None
    effect_size: str | None = None
    metric: list[str] = Field(default_factory=list)
    condition_context: list[str] = Field(default_factory=list)
    resource_mentions: list[str] = Field(default_factory=list)


class PaperLogicTrace(BaseModel):
    schema_version: str = Field(default='v1')
    paper_metadata: dict[str, Any]
    logic_steps: list[LogicStepTrace]
    claims: list[ClaimTrace]
    claim_evidence_links: list[dict[str, Any]] = Field(default_factory=list)
    figures: list[dict[str, Any]] = Field(default_factory=list)
    limitations: list[dict[str, Any]] = Field(default_factory=list)
    future_work_signals: list[dict[str, Any]] = Field(default_factory=list)
    citation_acts: list[dict[str, Any]] = Field(default_factory=list)
    quality_tier: str
