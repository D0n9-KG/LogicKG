"""Pydantic v2 response models for LLM output validation."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


# ── Logic + Claims extraction (logic_claims_v2.py) ──


class LogicStepItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    summary: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence_chunk_ids: list[str] = Field(default_factory=list)  # backward compat
    evidence_quotes: list[str] = Field(default_factory=list)     # new: verbatim quotes


class LogicClaimItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    step_type: str = ""
    claim_kinds: list[str] = Field(default_factory=list)


class LogicClaimsResponse(BaseModel):
    """Response from extract_logic_and_claims_v2."""
    model_config = ConfigDict(extra="allow")
    logic: dict[str, LogicStepItem] = Field(default_factory=dict)
    claims: list[LogicClaimItem] = Field(default_factory=list)


# ── Chunk claim extraction (orchestrator._extract_claims_from_chunk_llm) ──


class ChunkClaimItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    text: str = ""
    evidence_quote: str = ""
    step_type: str = ""
    claim_kinds: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ChunkClaimsResponse(BaseModel):
    """Response from chunk-level claim extraction."""
    model_config = ConfigDict(extra="allow")
    claims: list[ChunkClaimItem] = Field(default_factory=list)


# ── Batch chunk claim extraction (orchestrator._extract_claims_from_chunks_batch_llm) ──


class ChunkClaimsBatchItem(BaseModel):
    """Claims extracted from a single chunk within a batch response."""
    model_config = ConfigDict(extra="allow")
    chunk_id: str = ""
    claims: list[ChunkClaimItem] = Field(default_factory=list)


class ChunkClaimsBatchResponse(BaseModel):
    """Response from multi-chunk batch claim extraction."""
    model_config = ConfigDict(extra="allow")
    chunks: list[ChunkClaimsBatchItem] = Field(default_factory=list)


# ── Grounding judge (grounding_judge_v2.py) ──


class GroundingItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    canonical_claim_id: str = ""
    label: str = "unsupported"
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class GroundingJudgeResponse(BaseModel):
    """Response from grounding judge."""
    model_config = ConfigDict(extra="allow")
    items: list[GroundingItem] = Field(default_factory=list)


# ── Conflict judge (conflict_judge.py) ──


class ConflictPairItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    pair_id: str = ""
    label: str = "insufficient"
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class ConflictJudgeResponse(BaseModel):
    """Response from conflict judge."""
    model_config = ConfigDict(extra="allow")
    items: list[ConflictPairItem] = Field(default_factory=list)


# ── Citation purpose (citation_purpose.py) ──


class CitationPurposeItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    label: str = ""
    score: float = Field(default=0.5, ge=0.0, le=1.0)


class CitationPurposeResponse(BaseModel):
    """Response from single citation purpose classification."""
    model_config = ConfigDict(extra="allow")
    purposes: list[CitationPurposeItem] = Field(default_factory=list)


class BatchCitationItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    ref_id: str = ""
    purposes: list[CitationPurposeItem] = Field(default_factory=list)


class BatchCitationPurposeResponse(BaseModel):
    """Response from batch citation purpose classification."""
    model_config = ConfigDict(extra="allow")
    citations: list[BatchCitationItem] = Field(default_factory=list)


# ── Evidence pick (logic_claims_v2.py evidence verification) ──


class EvidencePickItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    claim_key: str = ""
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    weak: bool = False


class EvidencePickResponse(BaseModel):
    """Response from evidence pick/verification."""
    model_config = ConfigDict(extra="allow")
    items: list[EvidencePickItem] = Field(default_factory=list)
