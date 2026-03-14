from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field


_POSITIVE_PURPOSES = {'SupportEvidence', 'ExtendImprove', 'MethodUse', 'Theory', 'DataTool'}
_NEGATIVE_PURPOSES = {'CritiqueLimit'}
_GAP_HINT_PURPOSES = {'CritiqueLimit', 'ProblemSetup', 'FutureDirection'}
_FUTURE_HINT_PURPOSES = {'FutureDirection'}
_METHOD_TRANSFER_PURPOSES = {'ExtendImprove', 'MethodUse', 'DataTool'}
_BENCHMARK_HINT_PURPOSES = {'BaselineCompare'}


class CitationActRecord(BaseModel):
    citation_id: str
    citing_paper_id: str
    cited_paper_id: str
    total_mentions: int = 0
    ref_nums: list[int] = Field(default_factory=list)
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    evidence_spans: list[str] = Field(default_factory=list)
    purpose_labels: list[str] = Field(default_factory=list)
    purpose_scores: list[float] = Field(default_factory=list)
    polarity: str = 'neutral'
    semantic_signals: list[str] = Field(default_factory=list)
    target_scopes: list[str] = Field(default_factory=lambda: ['paper'])
    source: str = 'machine'


def _clean_labels(labels: Iterable[object] | None) -> list[str]:
    cleaned: list[str] = []
    for item in labels or []:
        value = str(item or '').strip()
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned


def _clean_scores(scores: Iterable[object] | None) -> list[float]:
    cleaned: list[float] = []
    for item in scores or []:
        try:
            cleaned.append(float(item))
        except Exception:
            cleaned.append(0.0)
    return cleaned


def derive_polarity(labels: Iterable[object] | None, scores: Iterable[object] | None = None) -> str:
    cleaned = _clean_labels(labels)
    if not cleaned:
        return 'neutral'
    positive = any(label in _POSITIVE_PURPOSES for label in cleaned)
    negative = any(label in _NEGATIVE_PURPOSES for label in cleaned)
    if positive and negative:
        return 'mixed'
    if negative:
        return 'negative'
    if positive:
        return 'positive'
    return 'neutral'


def derive_semantic_signals(labels: Iterable[object] | None, scores: Iterable[object] | None = None) -> list[str]:
    cleaned = _clean_labels(labels)
    signals: list[str] = []
    if any(label in _GAP_HINT_PURPOSES for label in cleaned):
        signals.append('gap_hint')
    if any(label in _FUTURE_HINT_PURPOSES for label in cleaned):
        signals.append('future_opportunity_hint')
    if any(label in _METHOD_TRANSFER_PURPOSES for label in cleaned):
        signals.append('method_transfer_hint')
    if any(label in _BENCHMARK_HINT_PURPOSES for label in cleaned):
        signals.append('benchmark_instability_hint')
    return signals


def derive_target_scopes(labels: Iterable[object] | None) -> list[str]:
    cleaned = _clean_labels(labels)
    scopes: list[str] = ['paper']
    if any(label in {'MethodUse', 'ExtendImprove', 'BaselineCompare'} for label in cleaned):
        scopes.append('method')
    if any(label in {'DataTool'} for label in cleaned):
        scopes.append('dataset')
    if any(label in {'SupportEvidence', 'CritiqueLimit', 'Theory'} for label in cleaned):
        scopes.append('claim')
    if any(label in {'FutureDirection', 'ProblemSetup'} for label in cleaned):
        scopes.append('gap')
    return scopes


def build_citation_act_record(
    *,
    citing_paper_id: str,
    cite_record: dict,
    purpose_item: dict | None = None,
) -> CitationActRecord:
    cited_paper_id = str(cite_record.get('cited_paper_id') or '').strip()
    labels = _clean_labels((purpose_item or {}).get('labels'))
    scores = _clean_scores((purpose_item or {}).get('scores'))
    return CitationActRecord(
        citation_id=f'citeact:{citing_paper_id}->{cited_paper_id}',
        citing_paper_id=str(citing_paper_id or '').strip(),
        cited_paper_id=cited_paper_id,
        total_mentions=int(cite_record.get('total_mentions') or 0),
        ref_nums=[int(item) for item in (cite_record.get('ref_nums') or []) if str(item).strip()],
        evidence_chunk_ids=[str(item) for item in (cite_record.get('evidence_chunk_ids') or []) if str(item).strip()],
        evidence_spans=[str(item) for item in (cite_record.get('evidence_spans') or []) if str(item).strip()],
        purpose_labels=labels,
        purpose_scores=scores,
        polarity=derive_polarity(labels, scores),
        semantic_signals=derive_semantic_signals(labels, scores),
        target_scopes=derive_target_scopes(labels),
        source='machine',
    )
