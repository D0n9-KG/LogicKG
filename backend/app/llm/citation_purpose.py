from __future__ import annotations

import json
import re
from typing import Any

from app.llm.client import call_json


PURPOSE_LABELS = [
    "Survey",
    "Background",
    "ProblemSetup",
    "Theory",
    "MethodUse",
    "DataTool",
    "BaselineCompare",
    "SupportEvidence",
    "CritiqueLimit",
    "ExtendImprove",
    "FutureDirection",
    "Unknown",  # LLM classification failed or returned invalid labels
]

_TPL_RE = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}")


def _render_template(template: str, vars: dict[str, Any]) -> str:
    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        v = vars.get(key)
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    return _TPL_RE.sub(_sub, template or "")


def _rule_int(rules: dict[str, Any], key: str, default: int, *, lo: int, hi: int) -> int:
    try:
        v = int(rules.get(key) if key in rules else default)
    except Exception:
        v = int(default)
    return max(lo, min(hi, v))


def _rule_float(rules: dict[str, Any], key: str, default: float, *, lo: float, hi: float) -> float:
    try:
        v = float(rules.get(key) if key in rules else default)
    except Exception:
        v = float(default)
    return max(lo, min(hi, v))


def classify_citation_purpose(
    citing_title: str,
    cited_title: str | None,
    cited_doi: str | None,
    contexts: list[str],
) -> dict:
    contexts = [c.strip() for c in contexts if c and c.strip()]
    contexts = contexts[:6]

    system = (
        "You classify the PURPOSE of a citation in a mechanics research paper.\n"
        "Return STRICT JSON only.\n"
        "Choose 1-3 labels from the allowed list and assign scores in [0,1] (higher=more likely).\n"
        "If evidence is insufficient, return label Background with low confidence.\n"
        f"Allowed labels: {', '.join(PURPOSE_LABELS)}"
    )
    user = (
        f"Citing paper title: {citing_title}\n"
        f"Cited paper title: {cited_title or ''}\n"
        f"Cited paper DOI: {cited_doi or ''}\n\n"
        "Evidence contexts (snippets around in-text citations):\n"
        + "\n---\n".join(contexts)
        + "\n\n"
        "Output JSON schema:\n"
        '{ "labels": ["MethodUse"], "scores": [0.72], "rationale": "short phrase" }\n'
    )
    out = call_json(system, user)
    labels = out.get("labels") or []
    scores = out.get("scores") or []
    if not isinstance(labels, list) or not labels:
        labels = ["Background"]
    if not isinstance(scores, list) or len(scores) != len(labels):
        scores = [0.4] * len(labels)
    # sanitize
    clean_labels = []
    clean_scores = []
    for l, s in zip(labels, scores):
        if l not in PURPOSE_LABELS:
            continue
        try:
            ss = float(s)
        except Exception:
            ss = 0.4
        ss = max(0.0, min(1.0, ss))
        clean_labels.append(l)
        clean_scores.append(ss)
    if not clean_labels:
        clean_labels = ["Background"]
        clean_scores = [0.4]
    # keep top 3
    pairs = sorted(zip(clean_labels, clean_scores), key=lambda x: x[1], reverse=True)[:3]
    return {"labels": [p[0] for p in pairs], "scores": [p[1] for p in pairs], "raw": out}


def _classify_batch_page(
    *,
    batch_items: list[dict],
    citing_title: str,
    system: str,
    user_template: str,
    fallback_score: float,
    max_labels: int,
) -> dict[str, Any]:
    """Run one LLM call for a batch page and return {cited_paper_id: {labels, scores}}."""
    if user_template:
        user = _render_template(
            user_template,
            {
                "citing_title": citing_title,
                "cites_json": json.dumps({"cites": batch_items}, ensure_ascii=False),
                "allowed_labels": ", ".join(PURPOSE_LABELS),
            },
        )
    else:
        user = (
            f"Citing paper title: {citing_title}\n\n"
            "For each citation, you are given the cited paper metadata (may be empty) and context snippets.\n"
            "Input JSON:\n"
            + json.dumps({"cites": batch_items}, ensure_ascii=False)
            + "\n\n"
            "Output JSON schema:\n"
            "{\n"
            '  "cites": [\n'
            '    {"cited_paper_id": "doi:10....", "labels": ["MethodUse"], "scores":[0.72]}\n'
            "  ]\n"
            "}\n"
        )

    out = call_json(system, user)
    rows = out.get("cites") or []
    by_id: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        cited_paper_id = row.get("cited_paper_id")
        if not cited_paper_id:
            continue
        labels = row.get("labels") or []
        scores = row.get("scores") or []
        if not isinstance(labels, list) or not labels:
            labels = ["Unknown"]
        if not isinstance(scores, list) or len(scores) != len(labels):
            scores = [fallback_score] * len(labels)
        clean_labels = []
        clean_scores = []
        for l, s in zip(labels, scores):
            if l not in PURPOSE_LABELS:
                continue
            try:
                ss = float(s)
            except Exception:
                ss = fallback_score
            ss = max(0.0, min(1.0, ss))
            clean_labels.append(l)
            clean_scores.append(ss)
        if not clean_labels:
            clean_labels = ["Unknown"]
            clean_scores = [0.0]
        pairs = sorted(zip(clean_labels, clean_scores), key=lambda x: x[1], reverse=True)[:max_labels]
        by_id[str(cited_paper_id)] = {
            "labels": [p[0] for p in pairs],
            "scores": [p[1] for p in pairs],
        }
    return {"by_id": by_id, "raw": out}


def classify_citation_purposes_batch(
    citing_title: str,
    cites: list[dict],
    max_contexts_per_cite: int = 3,
    max_context_chars: int = 900,
    prompt_overrides: dict[str, Any] | None = None,
    rules: dict[str, Any] | None = None,
    batch_size: int = 25,
) -> dict:
    """
    Classify purposes for many (A->B) citations, paginating into batches of batch_size.

    `cites` items:
      - cited_paper_id
      - cited_title (optional)
      - cited_doi (optional)
      - contexts: list[str]
    """
    if batch_size <= 0:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    rule_map = rules if isinstance(rules, dict) else {}
    max_contexts = _rule_int(
        rule_map,
        "citation_purpose_max_contexts_per_cite",
        max_contexts_per_cite,
        lo=1,
        hi=12,
    )
    max_context_len = _rule_int(
        rule_map,
        "citation_purpose_max_context_chars",
        max_context_chars,
        lo=120,
        hi=8000,
    )
    max_cites = _rule_int(
        rule_map,
        "citation_purpose_max_cites_per_batch",
        60,
        lo=1,
        hi=200,
    )
    max_labels = _rule_int(
        rule_map,
        "citation_purpose_max_labels_per_cite",
        3,
        lo=1,
        hi=8,
    )
    fallback_score = _rule_float(
        rule_map,
        "citation_purpose_fallback_score",
        0.4,
        lo=0.0,
        hi=1.0,
    )

    # Build sanitised item list (cap at max_cites)
    effective_cites = cites[:max_cites]
    items: list[dict] = []
    for c in effective_cites:
        ctxs = [x.strip() for x in (c.get("contexts") or []) if x and x.strip()]
        ctxs = [x[:max_context_len] for x in ctxs][:max_contexts]
        items.append(
            {
                "cited_paper_id": c.get("cited_paper_id"),
                "cited_title": c.get("cited_title") or "",
                "cited_doi": c.get("cited_doi") or "",
                "contexts": ctxs,
            }
        )

    default_system = (
        "You classify the PURPOSE of citations in a mechanics paper.\n"
        "Return STRICT JSON only.\n"
        "For each cited_paper_id, output 1-3 labels from the allowed list and scores in [0,1].\n"
        "Be conservative: if evidence is weak, use Background/Summary with low confidence.\n"
        f"Allowed labels: {', '.join(PURPOSE_LABELS)}"
    )
    ov = prompt_overrides if isinstance(prompt_overrides, dict) else {}
    system = str(ov.get("citation_purpose_batch_system") or "").strip() or default_system
    user_template = str(ov.get("citation_purpose_batch_user_template") or "").strip()

    by_id: dict[str, dict] = {}
    all_raw: list[Any] = []
    for batch_start in range(0, len(items), batch_size):
        batch = items[batch_start : batch_start + batch_size]
        page_result = _classify_batch_page(
            batch_items=batch,
            citing_title=citing_title,
            system=system,
            user_template=user_template,
            fallback_score=fallback_score,
            max_labels=max_labels,
        )
        by_id.update(page_result["by_id"])
        all_raw.append(page_result["raw"])

    return {"by_id": by_id, "raw": all_raw}
