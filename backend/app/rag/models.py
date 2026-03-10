from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Scope(BaseModel):
    mode: str = Field(default="all", description="all | collection | papers")
    collection_id: str | None = None
    paper_ids: list[str] | None = None


class AskV2Request(BaseModel):
    question: str = Field(min_length=1)
    k: int = Field(default=8, ge=1, le=20)
    scope: Scope | None = None
    locale: str | None = Field(
        default=None,
        description="UI locale hint (e.g. zh-CN, en-US) for answer language control.",
    )
    domain_prompt: str | None = Field(
        default=None,
        description="Custom domain context for the system prompt.",
    )


class EvidenceItem(BaseModel):
    chunk_id: str | None = None
    score: float | None = None
    paper_source: str | None = None
    paper_title: str | None = None
    md_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    section: str | None = None
    kind: str | None = None
    snippet: str | None = None
    mode: str | None = None
    rank: int | None = None
    paper_id: str | None = None
    rrf_score: float | None = None


class FusionEvidenceItem(BaseModel):
    paper_source: str | None = None
    paper_id: str | None = None
    logic_step_id: str | None = None
    step_type: str | None = None
    entity_id: str | None = None
    entity_name: str | None = None
    entity_type: str | None = None
    description: str | None = None
    score: float | None = None
    rank_score: float | None = None
    reasons: list[str] | None = None
    evidence_chunk_ids: list[str] | None = None
    source_chunk_id: str | None = None
    evidence_quote: str | None = None
    source_chapter_id: str | None = None
    textbook_id: str | None = None
    textbook_title: str | None = None
    chapter_id: str | None = None
    chapter_num: int | None = None
    chapter_title: str | None = None


class EvidenceBundle(BaseModel):
    evidence: list[EvidenceItem] = Field(default_factory=list)
    fusion_evidence: list[FusionEvidenceItem] = Field(default_factory=list)
    dual_evidence_coverage: bool = False
    retrieval_mode: str = "faiss"
    graph_context: list[dict[str, Any]] | None = None
    structured_knowledge: dict[str, list[dict[str, Any]]] | None = None
    insufficient_scope_evidence: bool = False
    message: str | None = None


class AskV2Response(BaseModel):
    answer: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    fusion_evidence: list[FusionEvidenceItem] = Field(default_factory=list)
    dual_evidence_coverage: bool = False
    retrieval_mode: str = "faiss"
    graph_context: list[dict[str, Any]] | None = None
    structured_knowledge: dict[str, list[dict[str, Any]]] | None = None
    insufficient_scope_evidence: bool = False
    message: str | None = None
