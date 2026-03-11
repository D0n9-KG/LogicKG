"""Noise filtering for extraction pipeline.

This module provides filters to detect and remove low-quality claims that should
not be processed as logic claims, including:
- Figure and table captions (e.g., "Figure 1: Experimental setup")
- Supplementary/appendix/subfigure captions (e.g., "Figure S1:", "Figure A1:")
- Scheme and algorithm captions (e.g., "Scheme 1:", "Algorithm 2:")
- Pure definitions (e.g., "X is a Y", "X refers to Y")

Additional features:
- Domain term whitelist: schema-configurable terms that bypass noise filters
- Context-aware definition filtering: definitions followed by comparative/causal
  sentences are preserved as they provide necessary context
"""
from __future__ import annotations

import re
from typing import Any


# Expanded caption pattern covering:
#   Standard:       "Figure 1:", "Table 12:", "Fig. 3:"
#   Supplementary:  "Supplementary Figure 1:", "Supplementary Table S2:"
#   S-prefix:       "Figure S1:", "Table S3:", "Fig. S2:"
#   Appendix:       "Figure A1:", "Table A2:"
#   Subfigures:     "Figure 1A:", "Figure 1a:", "Figure 12b:"
#   Scheme/Algo:    "Scheme 1:", "Algorithm 2:"
#   Listing/Box:    "Listing 1:", "Box 3:"
_CAPTION_PATTERN = re.compile(
    r"^\s*"
    r"(?:Supplementary\s+)?"                   # optional "Supplementary " prefix
    r"(?:Figure|Table|Fig\.|Scheme|Algorithm|Listing|Box)"
    r"\s+"
    r"(?:[SA]?)?"                               # optional S/A prefix on number
    r"\d+"                                      # main number
    r"[A-Za-z]?"                                # optional subfigure letter
    r"\s*:",
    re.IGNORECASE
)


# Definition patterns: "X is a Y", "X refers to Y", "X is defined as Y"
_DEFINITION_PATTERNS = [
    re.compile(r"\bis\s+a\s+", re.IGNORECASE),  # "is a"
    re.compile(r"\bis\s+the\s+", re.IGNORECASE),  # "is the"
    re.compile(r"\brefers?\s+to\s+", re.IGNORECASE),  # "refers to"
    re.compile(r"\bis\s+defined\s+as\s+", re.IGNORECASE),  # "is defined as"
    re.compile(r"\brepresents?\s+", re.IGNORECASE),  # "represents"
]

# Comparative/causal patterns (using \w* to catch inflections)
# Note: "lead" requires suffix to avoid matching "leadership"
_COMPARATIVE_PATTERN = re.compile(
    r'\b(better|worse|more|less|higher|lower|'
    r'outperform\w*|improv\w+|increas\w+|decreas\w+|'
    r'caus\w+|leads?|leading|led|result\w*)\b',
    re.IGNORECASE
)

# Strong definition markers that don't require is/are density check
_STRONG_DEFINITION_MARKERS = [
    re.compile(r"\brefers?\s+to\s+", re.IGNORECASE),
    re.compile(r"\bis\s+defined\s+as\s+", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Domain term whitelist
# ---------------------------------------------------------------------------

def _build_whitelist_pattern(terms: list[str]) -> re.Pattern[str] | None:
    """Build a compiled regex that matches any of the given domain terms.

    Returns None if the list is empty so callers can skip the check cheaply.
    Non-string entries are silently skipped.  Longer terms are matched first
    so that e.g. "discrete element" is tried before "element".
    Uses ``(?<!\\w)`` / ``(?!\\w)`` instead of ``\\b`` to correctly handle
    terms containing special characters (e.g. "C++").
    """
    if not terms:
        return None
    escaped: list[str] = []
    for term in terms:
        if not isinstance(term, str):
            continue
        normalized = term.strip()
        if not normalized:
            continue
        escaped.append(re.escape(normalized))

    if not escaped:
        return None

    escaped.sort(key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(escaped) + r")(?!\w)", re.IGNORECASE)


def _text_matches_whitelist(
    text: str, whitelist_re: re.Pattern[str] | None
) -> bool:
    """Return True if *text* contains a whitelisted domain term."""
    if whitelist_re is None:
        return False
    return whitelist_re.search(text) is not None


def is_caption_text(
    text: str | None,
    *,
    whitelist_re: re.Pattern[str] | None = None,
) -> bool:
    """Detect if text appears to be a figure or table caption.

    Covers standard, supplementary, appendix, subfigure, scheme, algorithm,
    listing, and box captions.  If *whitelist_re* is provided and the text
    contains a whitelisted domain term the caption filter is bypassed.

    Args:
        text: Claim text to check. Can be None.
        whitelist_re: Compiled pattern from ``_build_whitelist_pattern``.

    Returns:
        True if text starts with a caption pattern (and is not whitelisted).

    Examples:
        >>> is_caption_text("Figure 1: Experimental setup")
        True
        >>> is_caption_text("Supplementary Figure S2: Extra data")
        True
        >>> is_caption_text("Figure A1: Appendix result")
        True
        >>> is_caption_text("as shown in Figure 1")
        False
        >>> is_caption_text(None)
        False
    """
    if not isinstance(text, str):
        return False
    if _text_matches_whitelist(text, whitelist_re):
        return False
    return _CAPTION_PATTERN.match(text) is not None


def is_pure_definition_text(
    text: str | None,
    *,
    whitelist_re: re.Pattern[str] | None = None,
    next_text: str | None = None,
) -> bool:
    """Detect if text is a pure definition.

    Pure definitions have low semantic value for downstream relation mining.
    Examples: "X is a Y", "X refers to Y", "X is defined as Y"

    Context-aware rule: if *next_text* (the immediately following claim in the
    same chunk) contains a comparative or causal statement, the definition is
    preserved because it provides necessary context for the substantive claim.

    Heuristic:
    - Definition if (pattern_count >= 1 AND is/are density > 0.08, ~1 copula per 12 words)
      OR pattern_count >= 2
      OR contains strong definition markers ("refers to", "defined as")
    - Rejects comparative/causal statements (e.g., "outperforms", "causes")
    - Bypassed if text contains a whitelisted domain term

    Args:
        text: Claim text to check. Can be None.
        whitelist_re: Compiled pattern from ``_build_whitelist_pattern``.
        next_text: Text of the next claim in sequence (for context-aware filtering).

    Returns:
        True if text appears to be a pure definition (and should be filtered)
    """
    if not isinstance(text, str):
        return False

    # Whitelist bypass
    if _text_matches_whitelist(text, whitelist_re):
        return False

    text_lower = text.lower()

    # Reject comparative/causal statements (these are substantive claims)
    if _COMPARATIVE_PATTERN.search(text_lower):
        return False

    # Strong definition markers that don't require is/are density check
    if any(marker.search(text_lower) for marker in _STRONG_DEFINITION_MARKERS):
        return True

    # Count all definition patterns
    pattern_count = sum(1 for pattern in _DEFINITION_PATTERNS if pattern.search(text_lower))

    # Check for high is/are density (definition marker)
    is_are_count = len(re.findall(r'\b(is|are|was|were)\b', text_lower))
    total_words = len(text.split())

    if total_words == 0:
        return False

    is_are_density = is_are_count / total_words

    # Heuristic: definition if has pattern AND high is/are density
    # OR multiple definition patterns
    is_definition = (pattern_count >= 1 and is_are_density > 0.08) or pattern_count >= 2

    if not is_definition:
        return False

    # Context-aware: preserve definition if the next claim is comparative/causal
    # (the definition provides necessary context for the substantive claim)
    if isinstance(next_text, str) and next_text.strip():
        if _COMPARATIVE_PATTERN.search(next_text.lower()):
            return False

    return True


def _get_rule_bool(rules: Any, key: str, default: bool = False) -> bool:
    """Safely extract boolean rule value from dict or object.

    Handles string representations:
    "true"/"false", "1"/"0", "yes"/"no", "on"/"off".
    Aligned with orchestrator.py:_rule_bool() behavior.

    Args:
        rules: Rules object (dict or object with attributes)
        key: Rule key/attribute name
        default: Default value if key not found

    Returns:
        Parsed boolean value or default
    """
    if isinstance(rules, dict):
        raw = rules.get(key, None)
    else:
        raw = getattr(rules, key, None)

    if raw is None:
        return bool(default)
    if isinstance(raw, bool):
        return raw

    s = str(raw).strip().lower()
    if not s:
        return bool(default)
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def filter_claim_candidates(
    claims: list[dict[str, Any]],
    rules: Any  # SchemaRules, but avoid circular import
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Filter noise claims from candidates.

    Args:
        claims: List of claim dicts with 'text' field
        rules: SchemaRules with noise filter configuration (dict or object).
            Recognised keys:
            - ``phase1_noise_filter_enabled`` (bool)
            - ``phase1_noise_filter_figure_caption_enabled`` (bool)
            - ``phase1_noise_filter_pure_definition_enabled`` (bool)
            - ``phase1_noise_filter_domain_whitelist`` (list[str])
            - ``phase1_noise_filter_context_aware`` (bool, default True)

    Returns:
        (filtered_claims, stats) where stats contains:
        - raw_count: Original claim count
        - filtered_count: Remaining after filtering
        - caption_filtered: Count removed as captions
        - definition_filtered: Count removed as definitions
        - whitelist_preserved: Count preserved by domain whitelist
        - context_preserved: Count preserved by context-aware rule
        - filter_rate: Proportion filtered (0.0 - 1.0)
    """
    raw_count = len(claims)

    # Quick exit if filtering disabled
    if not _get_rule_bool(rules, 'phase1_noise_filter_enabled', False):
        return list(claims), {
            "raw_count": raw_count,
            "filtered_count": raw_count,
            "caption_filtered": 0,
            "definition_filtered": 0,
            "whitelist_preserved": 0,
            "context_preserved": 0,
            "filter_rate": 0.0,
        }

    caption_enabled = _get_rule_bool(rules, 'phase1_noise_filter_figure_caption_enabled', True)
    definition_enabled = _get_rule_bool(rules, 'phase1_noise_filter_pure_definition_enabled', True)
    context_aware = _get_rule_bool(rules, 'phase1_noise_filter_context_aware', True)

    # Build domain whitelist pattern
    wl_terms: list[str] = []
    if isinstance(rules, dict):
        wl_terms = rules.get("phase1_noise_filter_domain_whitelist") or []
    else:
        wl_terms = getattr(rules, "phase1_noise_filter_domain_whitelist", None) or []
    whitelist_re = _build_whitelist_pattern(wl_terms)

    filtered: list[dict[str, Any]] = []
    caption_filtered_count = 0
    definition_filtered_count = 0
    whitelist_preserved_count = 0
    context_preserved_count = 0

    for idx, claim in enumerate(claims):
        text = claim.get("text", "")
        text_is_whitelisted = isinstance(text, str) and _text_matches_whitelist(text, whitelist_re)
        counted_whitelist_preservation = False

        # Caption filter (with whitelist bypass)
        if caption_enabled:
            # Check if whitelist would save it
            if _CAPTION_PATTERN.match(text.lstrip() if isinstance(text, str) else ""):
                if text_is_whitelisted:
                    whitelist_preserved_count += 1
                    counted_whitelist_preservation = True
                else:
                    caption_filtered_count += 1
                    continue

        # Definition filter (with whitelist + context-aware bypass)
        if definition_enabled and isinstance(text, str) and text.strip():
            next_text = claims[idx + 1].get("text", "") if (context_aware and idx + 1 < len(claims)) else None
            if is_pure_definition_text(text, whitelist_re=whitelist_re, next_text=next_text):
                definition_filtered_count += 1
                continue
            # Track whitelist preservation for definitions
            if (
                text_is_whitelisted
                and not counted_whitelist_preservation
                and is_pure_definition_text(text, whitelist_re=None, next_text=next_text)
            ):
                whitelist_preserved_count += 1
                counted_whitelist_preservation = True
            # Track context-aware preservations: would have been filtered without context
            if context_aware and next_text and is_pure_definition_text(text, whitelist_re=whitelist_re, next_text=None):
                context_preserved_count += 1

        filtered.append(claim)

    filtered_count = len(filtered)
    filter_rate = (raw_count - filtered_count) / raw_count if raw_count > 0 else 0.0

    stats = {
        "raw_count": raw_count,
        "filtered_count": filtered_count,
        "caption_filtered": caption_filtered_count,
        "definition_filtered": definition_filtered_count,
        "whitelist_preserved": whitelist_preserved_count,
        "context_preserved": context_preserved_count,
        "filter_rate": filter_rate,
    }

    return filtered, stats
