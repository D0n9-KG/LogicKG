"""LLM-based paper type classifier with rule-based fallback."""
from __future__ import annotations

import logging
import re
from typing import Any

from app.schema_store import PaperType, coerce_paper_type

logger = logging.getLogger(__name__)

_VALID_TYPES = ("research", "review", "software", "theoretical", "case_study")

_SYSTEM_PROMPT = """\
You are a scientific paper classifier. Given the title, abstract (if available), \
and first section headings of a paper, classify it into exactly ONE of these types:

- research: Original experimental/empirical research with methods, experiments, and results
- review: Survey, literature review, or systematic review summarizing existing work
- software: Paper primarily describing a software tool, framework, library, or platform
- theoretical: Paper focused on mathematical models, proofs, or theoretical analysis without experiments
- case_study: Paper applying known methods to a specific real-world case or scenario

Respond with ONLY the type label (one word, lowercase). No explanation."""

_USER_TEMPLATE = """\
Title: {title}
Abstract: {abstract}
Section headings: {sections}

Paper type:"""

# ── Rule-based fallback keywords ──
_REVIEW_KW = re.compile(
    r"\b(review|survey|systematic\s+review|literature\s+review|meta[\-\s]?analysis|overview\s+of|state[\-\s]of[\-\s]the[\-\s]art)\b",
    re.IGNORECASE,
)
_SOFTWARE_KW = re.compile(
    r"\b(open[\-\s]?source|software|framework|library|toolkit|platform|package|implementation|code\s+available|github|repository)\b",
    re.IGNORECASE,
)
_THEORETICAL_KW = re.compile(
    r"\b(theorem|proof|lemma|corollary|analytical\s+solution|closed[\-\s]form|mathematical\s+model|theoretical\s+analysis)\b",
    re.IGNORECASE,
)
_CASE_STUDY_KW = re.compile(
    r"\b(case\s+study|field\s+study|field\s+application|real[\-\s]world\s+application|industrial\s+application)\b",
    re.IGNORECASE,
)


def _rule_based_classify(title: str, abstract: str, sections: list[str]) -> PaperType:
    """Keyword heuristic fallback. Returns 'research' if nothing matches."""
    combined = f"{title} {abstract} {' '.join(sections)}"
    if _REVIEW_KW.search(combined):
        return "review"
    if _SOFTWARE_KW.search(title):
        # Only match software keywords in title to reduce false positives
        return "software"
    if _THEORETICAL_KW.search(combined):
        return "theoretical"
    if _CASE_STUDY_KW.search(combined):
        return "case_study"
    return "research"


def classify_paper_type(
    title: str,
    abstract: str = "",
    section_headings: list[str] | None = None,
    *,
    meta_paper_type: str | None = None,
) -> PaperType:
    """
    Classify paper type with priority: meta.json > LLM > rule-based fallback.

    Args:
        title: Paper title
        abstract: Paper abstract (may be empty)
        section_headings: First N section headings from the paper
        meta_paper_type: Value from meta.json if available (highest priority)

    Returns:
        One of the valid PaperType values
    """
    # Priority 1: meta.json explicit type
    if meta_paper_type:
        coerced = coerce_paper_type(meta_paper_type)
        if coerced:
            logger.debug("paper_type from meta.json: %s", coerced)
            return coerced

    sections = section_headings or []
    sections_str = ", ".join(sections[:5]) if sections else "(none)"
    title = (title or "").strip() or "(untitled)"
    abstract = (abstract or "").strip()

    # Priority 2: LLM classification
    try:
        from app.llm.client import call_text

        user_msg = _USER_TEMPLATE.format(
            title=title,
            abstract=abstract[:1500] if abstract else "(not available)",
            sections=sections_str,
        )
        raw = call_text(_SYSTEM_PROMPT, user_msg, use_retry=True).strip().lower()
        # Extract first word in case LLM adds explanation
        first_word = raw.split()[0].strip(".,;:\"'") if raw else ""
        coerced = coerce_paper_type(first_word)
        if coerced:
            logger.info("paper_type from LLM: %s (raw=%r)", coerced, raw)
            return coerced
        logger.warning("LLM returned invalid paper_type: %r, falling back to rules", raw)
    except Exception:
        logger.warning("LLM paper_type classification failed, falling back to rules", exc_info=True)

    # Priority 3: Rule-based fallback
    result = _rule_based_classify(title, abstract, sections)
    logger.info("paper_type from rules: %s", result)
    return result


def extract_abstract_from_chunks(chunks: list[Any]) -> str:
    """Extract abstract text from parsed chunks (best-effort)."""
    for chunk in chunks[:10]:
        section = ""
        text = ""
        if isinstance(chunk, dict):
            section = str(chunk.get("section") or "").lower()
            text = str(chunk.get("text") or "")
        elif hasattr(chunk, "section"):
            section = str(getattr(chunk, "section", "") or "").lower()
            text = str(getattr(chunk, "text", "") or "")
        if "abstract" in section and len(text) > 50:
            return text
    return ""


def extract_section_headings_from_chunks(chunks: list[Any], max_headings: int = 5) -> list[str]:
    """Extract unique section headings from parsed chunks."""
    seen: set[str] = set()
    headings: list[str] = []
    for chunk in chunks:
        section = ""
        if isinstance(chunk, dict):
            section = str(chunk.get("section") or "").strip()
        elif hasattr(chunk, "section"):
            section = str(getattr(chunk, "section", "") or "").strip()
        if section and section not in seen:
            seen.add(section)
            headings.append(section)
            if len(headings) >= max_headings:
                break
    return headings
