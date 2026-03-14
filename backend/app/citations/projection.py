from __future__ import annotations

import json
from collections.abc import Iterable

from app.citations.models import build_citation_act_record


_SEMANTIC_SIGNAL_TO_PURPOSES = {
    'gap_hint': {'CritiqueLimit', 'ProblemSetup'},
    'future_opportunity_hint': {'FutureDirection'},
    'method_transfer_hint': {'ExtendImprove', 'MethodUse', 'DataTool'},
    'benchmark_instability_hint': {'BaselineCompare'},
}


def _label_score_map(labels: Iterable[object] | None, scores: Iterable[object] | None) -> dict[str, float]:
    label_list = [str(label or '').strip() for label in (labels or [])]
    score_list: list[float] = []
    for value in scores or []:
        try:
            score_list.append(float(value))
        except Exception:
            score_list.append(0.0)

    mapping: dict[str, float] = {}
    for index, label in enumerate(label_list):
        if not label:
            continue
        score = score_list[index] if index < len(score_list) else 0.0
        mapping[label] = max(mapping.get(label, 0.0), float(score))
    return mapping


def _signal_score_map(label_scores: dict[str, float]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for signal, labels in _SEMANTIC_SIGNAL_TO_PURPOSES.items():
        score = max((label_scores.get(label, 0.0) for label in labels), default=0.0)
        if score > 0.0:
            scores[signal] = float(score)
    return scores


def _json_map(payload: dict[str, float]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def build_citation_act_rows(
    *,
    paper_id: str,
    cites_resolved: list[dict] | None,
    purposes: list[dict] | None,
    source: str = 'machine',
) -> list[dict]:
    purpose_by_cited: dict[str, dict] = {}
    for item in purposes or []:
        cited_paper_id = str((item or {}).get('cited_paper_id') or '').strip()
        if cited_paper_id:
            purpose_by_cited[cited_paper_id] = dict(item)

    rows: list[dict] = []
    for cite_record in cites_resolved or []:
        cited_paper_id = str((cite_record or {}).get('cited_paper_id') or '').strip()
        if not cited_paper_id:
            continue
        purpose_item = purpose_by_cited.get(cited_paper_id) or {'labels': ['Unknown'], 'scores': [0.0]}
        act = build_citation_act_record(
            citing_paper_id=str(paper_id or '').strip(),
            cite_record=dict(cite_record),
            purpose_item=purpose_item,
        )
        label_scores = _label_score_map(act.purpose_labels, act.purpose_scores)
        signal_scores = _signal_score_map(label_scores)
        row = act.model_dump()
        row['source'] = source
        row['purpose_histogram_json'] = _json_map(label_scores)
        row['polarity_histogram_json'] = _json_map({act.polarity: 1.0})
        row['semantic_signal_histogram_json'] = _json_map(signal_scores)
        row['support_strength'] = float(label_scores.get('SupportEvidence', 0.0))
        row['critique_strength'] = float(label_scores.get('CritiqueLimit', 0.0))
        row['future_direction_strength'] = float(label_scores.get('FutureDirection', 0.0))
        row['extend_improve_strength'] = float(label_scores.get('ExtendImprove', 0.0))
        row['gap_signal_strength'] = float(signal_scores.get('gap_hint', 0.0))
        rows.append(row)
    return rows
