from __future__ import annotations

import math
import re
from typing import Any


SUPPORT_MARKERS = [
    "support",
    "consistent with",
    "agree with",
    "confirm",
    "corroborate",
    "证实",
    "一致",
    "支持",
]
CHALLENGE_MARKERS = [
    "however",
    "fails to",
    "cannot",
    "limitation",
    "inconsistent",
    "contrary",
    "conflict",
    "challenge",
    "不足",
    "局限",
    "并不",
    "不一致",
    "冲突",
    "挑战",
]
SUPERSEDE_MARKERS = [
    "outperform",
    "better than",
    "surpass",
    "replace",
    "supersede",
    "state-of-the-art",
    "sota",
    "significantly improve",
    "优于",
    "超过",
    "替代",
    "更好",
    "显著提升",
]

# High-ambiguity English challenge words matched via word boundary (not substring)
# to avoid false positives like "notation" or "notable".
_CHALLENGE_WORD_MARKERS = frozenset({"not", "but"})

# Relation-type inference thresholds (embedding similarity space)
_SUPERSEDE_KW_THRESH = 0.90
_SUPERSEDE_PURPOSE_THRESH = 0.86
_CHALLENGE_KW_THRESH = 0.90
_CHALLENGE_PURPOSE_THRESH = 0.86
_SUPPORT_KW_THRESH = 0.89
_SUPPORT_PURPOSE_THRESH = 0.88
_HIGH_SIM_THRESH = 0.97


_WS_RE = re.compile(r"\s+")


def normalize_proposition_text(text: str) -> str:
    s = _WS_RE.sub(" ", (text or "").strip().lower())
    while s and s[-1] in ".;銆傦紱":
        s = s[:-1].rstrip()
    return s


def clamp01(x: float) -> float:
    v = float(x)
    return max(0.0, min(1.0, v)) if math.isfinite(v) else 0.0


def contains_any(text: str, markers: list[str]) -> bool:
    t = text or ""
    return any(m in t for m in markers)


def _contains_word(text: str, word: str) -> bool:
    """Return True if *word* appears as a whole word in *text* (ASCII word boundary)."""
    t = text or ""
    if not t or not word:
        return False
    return re.search(rf"\b{re.escape(word)}\b", t) is not None


def _best_purpose_score(labels: list[str] | None, scores: list[float] | None, wanted: str) -> float:
    """Return the highest score among citations with the given purpose label."""
    labs = [str(x).strip() for x in (labels or []) if str(x).strip()]
    vals = list(scores or [])
    best = 0.0
    for idx, label in enumerate(labs):
        if label != wanted:
            continue
        try:
            raw = float(vals[idx]) if idx < len(vals) else 0.4
        except Exception:
            raw = 0.4
        best = max(best, clamp01(raw))
    return best


def infer_relation_type(
    source_text: str,
    target_text: str,
    similarity: float,
    target_confidence: float,
    *,
    citation_purpose_labels: list[str] | None = None,
    citation_purpose_scores: list[float] | None = None,
    min_similarity: float = 0.86,
    accepted_threshold: float = 0.82,
) -> dict[str, Any] | None:
    sim = clamp01(similarity)
    tgt_conf = clamp01(target_confidence)

    src = normalize_proposition_text(source_text)
    tgt = normalize_proposition_text(target_text)
    if not src or not tgt:
        return None

    # Text identity is highest-priority rule: merge even if similarity is low/noisy.
    if src == tgt:
        return {"event_type": "MERGE", "confidence": 0.99, "strength": 0.99, "status": "accepted", "reason": "text_identity"}

    if sim < min_similarity:
        return None

    base_conf = clamp01(0.65 * sim + 0.35 * tgt_conf)

    supersedes = contains_any(tgt, SUPERSEDE_MARKERS)
    challenges = contains_any(tgt, CHALLENGE_MARKERS) or any(
        _contains_word(tgt, w) for w in _CHALLENGE_WORD_MARKERS
    )
    supports = contains_any(tgt, SUPPORT_MARKERS)

    # Citation purpose scores from the LLM-extracted citation context.
    # These are more reliable signals than keyword matching in proposition text.
    p_supersede = _best_purpose_score(citation_purpose_labels, citation_purpose_scores, "ExtendImprove")
    p_challenge = _best_purpose_score(citation_purpose_labels, citation_purpose_scores, "CritiqueLimit")
    p_support = _best_purpose_score(citation_purpose_labels, citation_purpose_scores, "SupportEvidence")

    # SUPERSEDES: keyword match at high similarity OR strong ExtendImprove purpose signal
    if (supersedes and sim >= _SUPERSEDE_KW_THRESH) or (p_supersede >= 0.60 and sim >= _SUPERSEDE_PURPOSE_THRESH):
        conf = clamp01(base_conf + 0.06 + 0.05 * p_supersede)
        status = "accepted" if conf >= accepted_threshold else "pending_review"
        return {"event_type": "SUPERSEDES", "confidence": conf, "strength": conf, "status": status}

    # CHALLENGES: keyword match at high similarity OR strong CritiqueLimit purpose signal
    if (challenges and sim >= _CHALLENGE_KW_THRESH) or (p_challenge >= 0.55 and sim >= _CHALLENGE_PURPOSE_THRESH):
        conf = clamp01(base_conf + 0.04 + 0.06 * p_challenge)
        status = "accepted" if conf >= accepted_threshold else "pending_review"
        return {"event_type": "CHALLENGES", "confidence": conf, "strength": conf, "status": status}

    # SUPPORTS: keyword match OR SupportEvidence purpose signal
    if (supports and sim >= _SUPPORT_KW_THRESH) or (p_support >= 0.50 and sim >= _SUPPORT_PURPOSE_THRESH):
        conf = clamp01(base_conf + 0.03 + 0.04 * p_support)
        status = "accepted" if conf >= accepted_threshold else "pending_review"
        return {"event_type": "SUPPORTS", "confidence": conf, "strength": conf, "status": status}

    # High similarity alone suggests SUPPORTS
    if sim >= _HIGH_SIM_THRESH:
        conf = clamp01(base_conf)
        status = "accepted" if conf >= accepted_threshold else "pending_review"
        return {"event_type": "SUPPORTS", "confidence": conf, "strength": conf, "status": status}

    return None
