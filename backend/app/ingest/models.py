from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MdSpan:
    start_line: int
    end_line: int


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    paper_source: str
    md_path: str
    span: MdSpan
    section: str | None
    kind: str
    text: str


@dataclass(frozen=True)
class ReferenceEntry:
    paper_source: str
    md_path: str
    ref_num: int
    raw: str


@dataclass(frozen=True)
class CitationEvent:
    paper_source: str
    md_path: str
    cited_ref_num: int
    chunk_id: str
    span: MdSpan
    context: str


@dataclass(frozen=True)
class PaperDraft:
    paper_source: str
    md_path: str
    title: str | None
    title_alt: str | None
    authors: list[str]
    doi: str | None
    year: int | None
    paper_type: str | None = None


@dataclass(frozen=True)
class DocumentIR:
    paper: PaperDraft
    chunks: list[Chunk]
    references: list[ReferenceEntry]
    citations: list[CitationEvent]

