from __future__ import annotations

import re
from typing import Any


_LEADING_VERB_RE = re.compile(
    r'^(uses?|used|using|proposes?|proposed|presents?|presented|introduces?|introduced|'
    r'applies?|applied|employs?|employed|leverages?|leveraged)\s+',
    re.IGNORECASE,
)
_SPLIT_RE = re.compile(r'\b(?:for|to|via|through|with|by)\b', re.IGNORECASE)
_PUNCT_RE = re.compile(r'[^a-z0-9\s-]+')


def _normalize_text(text: object) -> str:
    return ' '.join(str(text or '').split()).strip()


def _extract_operation_or_method(summary: str) -> list[str]:
    text = _normalize_text(summary).lower()
    if not text:
        return []
    text = _LEADING_VERB_RE.sub('', text)
    text = _SPLIT_RE.split(text, maxsplit=1)[0]
    text = _PUNCT_RE.sub(' ', text)
    text = ' '.join(text.split()).strip('- ')
    if not text:
        return []
    return [text]


def normalize_logic_step(row: dict[str, Any]) -> dict[str, Any]:
    summary = _normalize_text(row.get('summary'))
    evidence = list(row.get('evidence') or [])
    evidence_chunk_ids = [
        str(item.get('chunk_id') or '').strip()
        for item in evidence
        if str(item.get('chunk_id') or '').strip()
    ]
    if not evidence_chunk_ids:
        evidence_chunk_ids = [
            str(item).strip()
            for item in (row.get('evidence_chunk_ids') or [])
            if str(item).strip()
        ]
    return {
        'logic_step_id': str(row.get('logic_step_id') or '').strip(),
        'step_type': str(row.get('step_type') or '').strip(),
        'summary': summary,
        'confidence': row.get('confidence'),
        'evidence': evidence,
        'evidence_chunk_ids': evidence_chunk_ids,
        'operation_or_method': _extract_operation_or_method(summary),
        'research_object': [],
        'observed_variable': [],
        'metric': [],
        'condition_context': [],
        'resource_mentions': [],
    }


def normalize_claim(row: dict[str, Any]) -> dict[str, Any]:
    targets = list(row.get('targets') or [])
    comparison_target = []
    for target in targets:
        label = str(target.get('title') or target.get('paper_id') or '').strip()
        if label:
            comparison_target.append(label)
    return {
        'claim_id': row.get('claim_id'),
        'claim_key': str(row.get('claim_key') or '').strip(),
        'text': _normalize_text(row.get('text')),
        'step_type': row.get('step_type'),
        'confidence': row.get('confidence'),
        'kinds': [str(item).strip() for item in (row.get('kinds') or []) if str(item).strip()],
        'evidence': list(row.get('evidence') or []),
        'targets': targets,
        'comparison_target': comparison_target,
        'effect_direction': None,
        'effect_size': None,
        'metric': [],
        'condition_context': [],
        'resource_mentions': [],
    }


def build_claim_evidence_links(claim_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for claim in claim_rows:
        claim_id = claim.get('claim_id')
        claim_key = str(claim.get('claim_key') or '').strip()
        for evidence in claim.get('evidence') or []:
            chunk_id = str(evidence.get('chunk_id') or '').strip()
            if not chunk_id:
                continue
            links.append(
                {
                    'claim_id': claim_id,
                    'claim_key': claim_key,
                    'chunk_id': chunk_id,
                    'section': evidence.get('section'),
                    'start_line': evidence.get('start_line'),
                    'end_line': evidence.get('end_line'),
                    'kind': evidence.get('kind'),
                    'source': evidence.get('source'),
                    'weak': bool(evidence.get('weak') or False),
                }
            )
    return links
