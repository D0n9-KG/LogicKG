from __future__ import annotations

import re
from collections import Counter
from typing import Any


_WORD_RE = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)?', re.IGNORECASE)
_GENERIC_TOKENS = {
    'a',
    'an',
    'approach',
    'for',
    'method',
    'methods',
    'model',
    'of',
    'paper',
    'problem',
    'proposes',
    'reasoning',
    'representation',
    'representations',
    'result',
    'results',
    'study',
    'system',
    'the',
    'this',
    'to',
    'uses',
    'using',
}


def _tokenize(text: object) -> list[str]:
    return [token.lower() for token in _WORD_RE.findall(str(text or '').lower())]


def _candidate_phrases(summary: str) -> list[str]:
    words = _tokenize(summary)
    phrases: list[str] = []
    for size in (3, 2):
        for index in range(len(words) - size + 1):
            window = words[index : index + size]
            if all(token in _GENERIC_TOKENS for token in window):
                continue
            phrases.append(' '.join(window))
    return phrases


def label_community(core_members: list[dict[str, Any]], claim_rows: list[dict[str, Any]]) -> dict[str, Any]:
    phrase_counter: Counter[str] = Counter()
    word_counter: Counter[str] = Counter()

    for row in core_members:
        summary = str(row.get('summary') or '').strip()
        for phrase in _candidate_phrases(summary):
            phrase_counter[phrase] += 1
        for token in _tokenize(summary):
            if token not in _GENERIC_TOKENS:
                word_counter[token] += 1

    title = ''
    if phrase_counter:
        title = max(phrase_counter.items(), key=lambda item: (item[1], len(item[0]), item[0]))[0]
    elif word_counter:
        title = ' '.join(token for token, _count in word_counter.most_common(3))
    else:
        title = 'cross-paper logic pattern'

    keywords = [title]
    for token, _count in word_counter.most_common(5):
        if token not in keywords:
            keywords.append(token)

    summary = f'Cross-paper logic steps centered on {title}.'
    if claim_rows:
        summary = f'{summary} Supported by {len(claim_rows)} related claims.'

    return {
        'title': title,
        'summary': summary,
        'keywords': keywords[:5],
    }
