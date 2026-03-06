"""Text normalization utilities for encoding recovery and symbol folding."""
from __future__ import annotations

import re

# Markers commonly seen when UTF-8 text is mis-decoded as GBK/CP936.
# We keep this conservative and only use it as a trigger heuristic.
_MOJIBAKE_MARKERS = (
    "寮曡█",   # 引言
    "鎽樿",   # 摘要
    "鍙傝€冩枃鐚",  # 参考文献
    "鍩",       # often appears in mojibake Chinese headings
    "銆",       # malformed punctuation cluster
    "锛",
    "锟",
    "鈥",
)

# Common symbol confusables observed in claims/chunks.
# Keep 1:1 replacements so index-based matching remains stable.
_SYMBOL_CONFUSABLES = str.maketrans(
    {
        "胃": "θ",
        "惟": "Ω",
        "伪": "α",
        "尾": "β",
        "纬": "γ",
        "渭": "μ",
        "蟽": "σ",
        "掳": "°",
    }
)


def _marker_score(text: str) -> int:
    s = text or ""
    return sum(s.count(token) for token in _MOJIBAKE_MARKERS)


def maybe_recover_utf8_as_gbk_mojibake(text: str) -> str:
    """Recover text that was likely decoded as GBK from UTF-8 bytes.

    Strategy:
    - only attempt recovery when mojibake markers are sufficiently frequent
    - reverse by gb18030-encode -> utf-8-decode
    - accept candidate only if marker score is clearly improved
    """
    raw = text or ""
    raw_score = _marker_score(raw)
    if raw_score < 3:
        return raw

    try:
        candidate = raw.encode("gb18030", errors="strict").decode("utf-8", errors="strict")
    except UnicodeError:
        return raw

    if not candidate:
        return raw

    cand_score = _marker_score(candidate)
    if cand_score + 1 <= raw_score:
        return candidate
    return raw


def normalize_ingested_markdown(text: str) -> str:
    """Ingestion-stage normalization:
    - recover UTF-8/GBK mojibake when confidently detected
    """
    return maybe_recover_utf8_as_gbk_mojibake(text or "")


def fold_symbol_confusables(text: str) -> str:
    """Span-matching-only symbol folding (no semantic rewrite)."""
    return (text or "").translate(_SYMBOL_CONFUSABLES)


def normalize_formula_for_matching(text: str) -> str:
    """Formula normalization for span matching only (symmetric, view-only).

    Handles common formula format differences:
    - LaTeX commands: \\mathrm{}, \\text{}, \\mathbf{}, \\operatorname{}
    - Spaces in formulas: "σ 1" vs "σ1"
    - Greek letter variants: θ/theta, α/alpha, β/beta, γ/gamma, μ/mu, σ/sigma

    This is applied symmetrically to both claim and chunk during matching,
    but does NOT modify stored text.
    """
    s = text or ""

    # Remove LaTeX commands (keep content) - allow optional spaces
    s = re.sub(r"\\mathrm\s*\{([^}]+)\}", r"\1", s)
    s = re.sub(r"\\text\s*\{([^}]+)\}", r"\1", s)
    s = re.sub(r"\\mathbf\s*\{([^}]+)\}", r"\1", s)
    s = re.sub(r"\\operatorname\s*\{([^}]+)\}", r"\1", s)

    # Remove spaces around formula elements (but keep sentence spaces)
    # Pattern: space between single char and digit/symbol
    s = re.sub(r"([α-ωΑ-Ωθσμγβ])\s+([0-9])", r"\1\2", s)
    s = re.sub(r"([0-9])\s+([α-ωΑ-Ωθσμγβ])", r"\1\2", s)

    # Greek letter normalization with word boundaries (only LaTeX-style)
    # Only replace when preceded by backslash to avoid false positives
    s = re.sub(r"\\theta\b", "θ", s)
    s = re.sub(r"\\Theta\b", "Θ", s)
    s = re.sub(r"\\alpha\b", "α", s)
    s = re.sub(r"\\Alpha\b", "Α", s)
    s = re.sub(r"\\beta\b", "β", s)
    s = re.sub(r"\\Beta\b", "Β", s)
    s = re.sub(r"\\gamma\b", "γ", s)
    s = re.sub(r"\\Gamma\b", "Γ", s)
    s = re.sub(r"\\delta\b", "δ", s)
    s = re.sub(r"\\Delta\b", "Δ", s)
    s = re.sub(r"\\epsilon\b", "ε", s)
    s = re.sub(r"\\Epsilon\b", "Ε", s)
    s = re.sub(r"\\mu\b", "μ", s)
    s = re.sub(r"\\Mu\b", "Μ", s)
    s = re.sub(r"\\sigma\b", "σ", s)
    s = re.sub(r"\\Sigma\b", "Σ", s)
    s = re.sub(r"\\omega\b", "ω", s)
    s = re.sub(r"\\Omega\b", "Ω", s)

    return s
