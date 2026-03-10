from __future__ import annotations

import re
from typing import Any


_TOKEN_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")
_SPACE_RE = re.compile(r"\s+")

_STEP_HINTS: dict[str, set[str]] = {
    "background": {"background", "context", "definition", "概念", "背景"},
    "problem": {"problem", "challenge", "question", "问题"},
    "method": {"method", "approach", "algorithm", "technique", "how", "方法", "算法"},
    "experiment": {"experiment", "evaluation", "test", "benchmark", "实验", "评估"},
    "result": {"result", "finding", "performance", "improve", "结论", "结果"},
    "conclusion": {"conclusion", "summary", "implication", "结论", "总结"},
}


def _normalize_text(value: str) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip())


def _tokens(value: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(str(value or ""))}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter <= 0:
        return 0.0
    return inter / max(1, len(a | b))


def _step_affinity(question_tokens: set[str], step_type: str) -> float:
    step_norm = _normalize_text(step_type).lower()
    hints = _STEP_HINTS.get(step_norm)
    if not hints:
        return 0.0
    if question_tokens & hints:
        return 1.0
    return 0.0


def rank_fusion_basics(
    question: str,
    rows: list[dict[str, Any]],
    *,
    k: int = 8,
) -> list[dict[str, Any]]:
    q_tokens = _tokens(question)
    scored: list[dict[str, Any]] = []

    for row in rows:
        text_blob = " ".join(
            [
                str(row.get("entity_name") or ""),
                str(row.get("description") or ""),
                str(row.get("evidence_quote") or ""),
                str(row.get("entity_type") or ""),
                str(row.get("step_type") or ""),
            ]
        )
        lexical = _jaccard(q_tokens, _tokens(text_blob))
        step_bonus = _step_affinity(q_tokens, str(row.get("step_type") or ""))
        base_score = float(row.get("score") or 0.0)
        rank_score = 0.45 * base_score + 0.35 * lexical + 0.20 * step_bonus
        out = dict(row)
        out["rank_score"] = round(rank_score, 6)
        scored.append(out)

    scored.sort(
        key=lambda x: (
            -float(x.get("rank_score") or 0.0),
            -float(x.get("score") or 0.0),
            str(x.get("entity_name") or ""),
        )
    )
    return scored[: max(1, int(k))]


def fusion_rows_to_structured_hits(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        entity_id = str(row.get("entity_id") or "").strip()
        entity_name = _normalize_text(str(row.get("entity_name") or ""))
        description = _normalize_text(str(row.get("description") or ""))
        if not entity_id or not (entity_name or description):
            continue
        text = entity_name
        if description:
            text = f"{entity_name}: {description}" if entity_name else description
        try:
            score = float(row.get("rank_score") or row.get("score") or 0.0)
        except Exception:
            score = 0.0
        hits.append(
            {
                "kind": "textbook",
                "source_id": entity_id,
                "id": entity_id,
                "text": text,
                "score": score,
                "paper_source": str(row.get("paper_source") or "").strip() or None,
                "paper_id": str(row.get("paper_id") or "").strip() or None,
                "source_kind": "textbook_entity",
                "source_ref_id": entity_id,
                "textbook_id": str(row.get("textbook_id") or "").strip() or None,
                "chapter_id": str(row.get("chapter_id") or row.get("source_chapter_id") or "").strip() or None,
            }
        )
    return hits


def format_fusion_evidence_block(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "Textbook Fundamentals:\n- (none)"

    lines = ["Textbook Fundamentals:"]
    for idx, row in enumerate(rows[:12], start=1):
        paper_source = str(row.get("paper_source") or "").strip()
        step_type = str(row.get("step_type") or "").strip()
        entity_name = str(row.get("entity_name") or "").strip()
        entity_type = str(row.get("entity_type") or "").strip()
        score = float(row.get("score") or 0.0)
        quote = _normalize_text(str(row.get("evidence_quote") or ""))
        if len(quote) > 220:
            quote = quote[:217].rstrip() + "..."

        parts = [f"[T{idx}]"]
        if paper_source:
            parts.append(paper_source)
        if step_type:
            parts.append(step_type)
        if entity_name:
            parts.append(entity_name)
        if entity_type:
            parts.append(f"<{entity_type}>")
        parts.append(f"(score={score:.3f})")
        if quote:
            parts.append(f"quote={quote}")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def has_dual_evidence(*, paper_evidence_count: int, textbook_evidence_count: int) -> bool:
    return int(paper_evidence_count) > 0 and int(textbook_evidence_count) > 0
