from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from app.llm.client import call_validated_json
from app.discovery.prompt_policy import choose_prompt_variants
from app.settings import settings


class _GeneratedQuestionItem(BaseModel):
    question: str = Field(min_length=10)
    motivation: str = Field(min_length=10)
    novelty: str = Field(min_length=10)
    proposed_method: str = Field(min_length=10)
    difference: str = Field(min_length=10)
    feasibility: str = Field(min_length=10)
    risk_statement: str | None = None
    evaluation_metrics: list[str] = Field(default_factory=list)
    timeline: str | None = None
    novelty_score: float = 0.0
    feasibility_score: float = 0.0
    relevance_score: float = 0.0
    generation_confidence: float = 0.0


class _GeneratedQuestionPayload(BaseModel):
    items: list[_GeneratedQuestionItem] = Field(default_factory=list)


_SPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_SENTENCE_SPLIT_RE = re.compile(r"(?<!\d)[.!?;。！？；]+(?!\d)")
_GENERIC_TOPIC_RE = re.compile(r"(signal from claim|extracted gap seed|open mechanism gap)", flags=re.IGNORECASE)
_TRAILING_WEAK_WORDS = {
    "and",
    "or",
    "to",
    "of",
    "for",
    "in",
    "on",
    "with",
    "without",
    "do",
    "does",
    "did",
    "not",
    "can",
    "cannot",
    "is",
    "are",
    "be",
}


def _normalize_text(text: str, *, limit: int = 400, add_ellipsis: bool = True) -> str:
    merged = _SPACE_RE.sub(" ", str(text or "")).strip()
    if len(merged) <= limit:
        return merged
    clipped = merged[: max(1, limit)].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip()
    if not add_ellipsis:
        return clipped
    return clipped + "..."


def _question_slug(text: str) -> str:
    normalized = _normalize_text(text, limit=512).lower()
    return hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:14]


def _tokens(text: str) -> set[str]:
    return set(_WORD_RE.findall(str(text or "").lower()))


def _topic_snippet(gap: dict, *, max_words: int = 18, max_chars: int = 140) -> str:
    candidates = [
        str(gap.get("description") or ""),
        str(gap.get("title") or ""),
        str(gap.get("missing_evidence_statement") or ""),
    ]
    base = ""
    for raw in candidates:
        merged = _SPACE_RE.sub(" ", str(raw or "")).strip()
        if merged and _GENERIC_TOPIC_RE.search(merged):
            continue
        if merged:
            base = merged
            break
    if not base:
        return "this unresolved phenomenon"

    first_sentence = _SENTENCE_SPLIT_RE.split(base, maxsplit=1)[0].strip()
    snippet = first_sentence or base
    words = snippet.split()
    if len(words) > max_words:
        snippet = " ".join(words[:max_words])
    if len(snippet) > max_chars:
        clipped = snippet[:max_chars]
        if " " in clipped:
            clipped = clipped.rsplit(" ", 1)[0]
        snippet = clipped
    snippet = snippet.rstrip(" ,;:.-")
    words2 = snippet.split()
    while len(words2) >= 4 and words2[-1].lower() in _TRAILING_WEAK_WORDS:
        words2.pop()
    snippet = " ".join(words2).rstrip(" ,;:.-")
    return snippet or "this unresolved phenomenon"


def _issue_phrase(topic: str) -> str:
    cleaned = _normalize_text(topic, limit=160, add_ellipsis=False).strip().rstrip("?.!,;:")
    if not cleaned:
        return "this unresolved phenomenon"
    if cleaned.lower().startswith(("the ", "a ", "an ")):
        return cleaned
    return f"the issue that {cleaned}"


def _pick_phrase(gap: dict, options: list[str], variant: int) -> str:
    if not options:
        return ""
    seed = (
        str(gap.get("gap_id") or "")
        or str(gap.get("title") or "")
        or str(gap.get("description") or "")
        or "seed"
    )
    h = int(hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:8], 16)
    idx = (h + max(0, int(variant) - 1)) % len(options)
    return options[idx]


def _context_overlap_score(payload: dict, item: _GeneratedQuestionItem) -> float:
    gap_text = " ".join(
        [
            str(payload.get("title") or ""),
            str(payload.get("description") or ""),
            str(payload.get("missing_evidence_statement") or ""),
            str(payload.get("graph_context_summary") or ""),
            " ".join(str(x) for x in (payload.get("rag_context_snippets") or [])),
        ]
    )
    ctx = _tokens(gap_text)
    if not ctx:
        return 0.0
    answer_text = " ".join(
        [
            str(item.question or ""),
            str(item.motivation or ""),
            str(item.novelty or ""),
            str(item.proposed_method or ""),
            str(item.difference or ""),
            str(item.feasibility or ""),
        ]
    )
    used = ctx.intersection(_tokens(answer_text))
    return max(0.0, min(1.0, len(used) / max(5.0, min(30.0, float(len(ctx))))))


def _default_question(gap: dict, variant: int) -> str:
    topic = _topic_snippet(gap, max_words=18, max_chars=140)
    issue = _issue_phrase(topic)
    gap_type = str(gap.get("gap_type") or "seed")
    if gap_type == "conflict_hotspot":
        stem = _pick_phrase(
            gap,
            [
                "Which causal pathway can reconcile conflicting evidence in",
                "Under which boundary conditions can contradictory findings converge on",
                "What falsifiable mechanism can explain disagreement around",
            ],
            variant=variant,
        )
        return f"{stem} {issue}?"
    if gap_type == "future_work":
        stem = _pick_phrase(
            gap,
            [
                "What minimal experiment can validate progress on",
                "How can we operationalize and benchmark advances in",
                "Which short-cycle study would de-risk the roadmap for",
            ],
            variant=variant,
        )
        return f"{stem} {issue}?"
    if gap_type == "limitation":
        stem = _pick_phrase(
            gap,
            [
                "How can we break the bottleneck in",
                "What design change could remove constraints in",
                "Which intervention can resolve the key limitation in",
            ],
            variant=variant,
        )
        return f"{stem} {issue} while preserving core performance?"
    if gap_type == "challenged_proposition":
        stem = _pick_phrase(
            gap,
            [
                "What evidence chain can stabilize claims about",
                "Which new experiment can re-evaluate the challenged proposition in",
                "How can we stress-test uncertainty in",
            ],
            variant=variant,
        )
        return f"{stem} {issue}?"
    if "friction" in topic.lower():
        return "How does contact friction causally alter clustering transition under controlled restitution settings?"
    if "temperature" in topic.lower():
        return "How does granular temperature interact with shear-banding onset across simulation and experimental regimes?"
    stem = _pick_phrase(
        gap,
        [
            "What testable mechanism can explain",
            "Which causal hypothesis best accounts for",
            "What boundary condition could resolve uncertainty in",
        ],
        variant=variant,
    )
    return f"{stem} {issue}?"


def _template_candidate(gap: dict, *, index: int, variant: int) -> dict:
    question = _normalize_text(_default_question(gap, variant), limit=320, add_ellipsis=False)
    gap_desc = _normalize_text(str(gap.get("description") or ""), limit=300)
    missing = _normalize_text(str(gap.get("missing_evidence_statement") or ""), limit=240)
    gap_type = str(gap.get("gap_type") or "seed")
    priority = float(gap.get("priority_score") or 0.5)

    novelty_score = max(0.35, min(0.95, 0.45 + priority * 0.4))
    feasibility_score = max(0.35, min(0.95, 0.72 - 0.2 * abs(0.6 - priority)))
    relevance_score = max(0.35, min(0.95, 0.5 + priority * 0.45))

    return {
        "candidate_id": f"rq:{index}:{variant}:{_question_slug(question)}",
        "question": question,
        "gap_id": str(gap.get("gap_id") or ""),
        "gap_type": gap_type,
        "motivation": f"Current literature exposes a high-value unresolved issue: {gap_desc}",
        "novelty": "Integrate conflicting/supporting signals into a condition-aware hypothesis and test explicit boundary conditions instead of average-case claims.",
        "proposed_method": "Build a cross-paper evidence matrix, define controllable variables, run stratified validation, and report mechanism-level causal indicators.",
        "difference": "Moves from descriptive gap statements to executable, evidence-linked scientific questions with explicit validation protocol.",
        "feasibility": "Feasible with current pipeline by reusing extracted claims, community memberships, and evidence chunks as the experimental design substrate.",
        "risk_statement": "Potential risk: signal sparsity or noisy extraction may bias hypothesis framing.",
        "evaluation_metrics": [
            "evidence_coverage_ratio",
            "cross_paper_consistency_gain",
            "challenge_resolution_rate",
        ],
        "timeline": "medium-term (4-8 weeks)",
        "novelty_score": novelty_score,
        "feasibility_score": feasibility_score,
        "relevance_score": relevance_score,
        "generation_mode": "template",
        "prompt_variant": "template_base",
        "generation_confidence": 0.58,
        "optimization_score": float(round(0.5 * novelty_score + 0.3 * feasibility_score + 0.2 * relevance_score, 4)),
        "source_claim_ids": list(gap.get("source_claim_ids") or []),
        "source_community_ids": list(gap.get("source_community_ids") or []),
        "source_paper_ids": list(gap.get("source_paper_ids") or []),
        "inspiration_adjacent_paper_ids": list(gap.get("inspiration_adjacent_paper_ids") or []),
        "inspiration_random_paper_ids": list(gap.get("inspiration_random_paper_ids") or []),
        "inspiration_community_paper_ids": list(gap.get("inspiration_community_paper_ids") or []),
        "graph_context_summary": _normalize_text(
            json.dumps(gap.get("signals") or {}, ensure_ascii=False),
            limit=220,
        ),
        "rag_context_snippets": [missing] if missing else [],
    }


def _llm_candidates_for_gap(
    gap: dict,
    *,
    domain: str,
    index: int,
    candidates_per_gap: int,
    optimize_prompt: bool,
    prompt_optimization_method: str,
) -> list[dict]:
    if not settings.effective_llm_api_key():
        return []

    graph_context_summary = _normalize_text(str(gap.get("graph_context_summary") or ""), limit=700)
    rag_context_snippets = [_normalize_text(str(x), limit=240) for x in (gap.get("rag_context_snippets") or []) if _normalize_text(str(x), limit=240)]
    payload = {
        "gap_id": str(gap.get("gap_id") or ""),
        "gap_type": str(gap.get("gap_type") or "seed"),
        "title": _normalize_text(str(gap.get("title") or "")),
        "description": _normalize_text(str(gap.get("description") or "")),
        "missing_evidence_statement": _normalize_text(str(gap.get("missing_evidence_statement") or "")),
        "priority_score": float(gap.get("priority_score") or 0.5),
        "signals": gap.get("signals") or {},
        "source_claim_ids": list(gap.get("source_claim_ids") or []),
        "source_community_ids": list(gap.get("source_community_ids") or []),
        "source_paper_ids": list(gap.get("source_paper_ids") or []),
        "graph_context_summary": graph_context_summary,
        "rag_context_snippets": rag_context_snippets,
    }

    def _prompt_for_style(style: str) -> tuple[str, str]:
        if style == "optimized":
            system = (
                "You are an expert research innovator specializing in interdisciplinary synthesis.\n"
                "Return STRICT JSON only.\n"
                "Generate testable scientific questions by integrating gap signals with graph-level context and local evidence snippets.\n"
                "Each item must include: question, motivation, novelty, proposed_method, difference, feasibility.\n"
                "Also provide risk_statement, evaluation_metrics (1-4 items), timeline, and three scores in [0,1]: novelty_score, feasibility_score, relevance_score.\n"
                "Prioritize concrete validation plans and explicit use of provided context."
            )
            user = (
                f"Generate {max(1, min(3, int(candidates_per_gap)))} candidate scientific questions.\n\n"
                "Gap JSON:\n"
                f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
                "Requirements:\n"
                "- Create synergy between the gap and at least one contextual adjacency.\n"
                "- Address either explicit limitation or unresolved conflict from the gap.\n"
                "- Include 1-2 measurable evaluation metrics and a realistic timeline.\n\n"
                "Output schema:\n"
                "{\n"
                '  "items": [\n'
                '    {\n'
                '      "question":"...", "motivation":"...", "novelty":"...", "proposed_method":"...",\n'
                '      "difference":"...", "feasibility":"...", "risk_statement":"...",\n'
                '      "evaluation_metrics":["..."], "timeline":"...",\n'
                '      "novelty_score":0.0, "feasibility_score":0.0, "relevance_score":0.0,\n'
                '      "generation_confidence":0.0\n'
                "    }\n"
                "  ]\n"
                "}"
            )
            return system, user

        system = (
            "You are a scientific-question generation engine.\n"
            "Return STRICT JSON only.\n"
            "Generate actionable, testable research questions from a given knowledge gap.\n"
            "Each item must include: question, motivation, novelty, proposed_method, difference, feasibility.\n"
            "Also provide risk_statement, evaluation_metrics (1-4 items), timeline, and three scores in [0,1]: novelty_score, feasibility_score, relevance_score.\n"
            "Avoid vague statements and avoid repeating the same question wording."
        )
        user = (
            f"Generate {max(1, min(3, int(candidates_per_gap)))} candidate scientific questions.\n\n"
            "Gap JSON:\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Output schema:\n"
            "{\n"
            '  "items": [\n'
            '    {\n'
            '      "question":"...", "motivation":"...", "novelty":"...", "proposed_method":"...",\n'
            '      "difference":"...", "feasibility":"...", "risk_statement":"...",\n'
            '      "evaluation_metrics":["..."], "timeline":"...",\n'
            '      "novelty_score":0.0, "feasibility_score":0.0, "relevance_score":0.0,\n'
            '      "generation_confidence":0.0\n'
            "    }\n"
            "  ]\n"
            "}"
        )
        return system, user

    def _invoke_style(style: str) -> list[tuple[_GeneratedQuestionItem, float]]:
        system, user = _prompt_for_style(style)
        try:
            parsed = call_validated_json(system=system, user=user, model_class=_GeneratedQuestionPayload, max_retries=1)
        except Exception:
            return []
        rows: list[tuple[_GeneratedQuestionItem, float]] = []
        for item in parsed.items[: max(1, min(3, int(candidates_per_gap)))]:
            ctx_overlap = _context_overlap_score(payload, item)
            model_quality = (
                0.3 * max(0.0, min(1.0, float(item.novelty_score or 0.0)))
                + 0.2 * max(0.0, min(1.0, float(item.feasibility_score or 0.0)))
                + 0.2 * max(0.0, min(1.0, float(item.relevance_score or 0.0)))
                + 0.2 * max(0.0, min(1.0, float(item.generation_confidence or 0.0)))
                + 0.1 * ctx_overlap
            )
            rows.append((item, float(round(model_quality, 4))))
        return rows

    method = str(prompt_optimization_method or "rl_bandit").strip().lower()
    if optimize_prompt:
        styles = choose_prompt_variants(
            domain=domain,
            gap_type=str(gap.get("gap_type") or "seed"),
            top_k=max(2, min(4, int(candidates_per_gap))),
            method=method,
        )
    else:
        styles = ["base"]

    all_items: list[dict] = []
    for style in styles:
        for idx_in_style, (item, opt_score) in enumerate(_invoke_style(style), start=1):
            q = _normalize_text(item.question, limit=320, add_ellipsis=False)
            all_items.append(
                {
                    "candidate_id": f"rq:{index}:{style}:{idx_in_style}:{_question_slug(q)}",
                    "question": q,
                    "gap_id": str(gap.get("gap_id") or ""),
                    "gap_type": str(gap.get("gap_type") or "seed"),
                    "motivation": _normalize_text(item.motivation, limit=500),
                    "novelty": _normalize_text(item.novelty, limit=500),
                    "proposed_method": _normalize_text(item.proposed_method, limit=500),
                    "difference": _normalize_text(item.difference, limit=500),
                    "feasibility": _normalize_text(item.feasibility, limit=500),
                    "risk_statement": _normalize_text(item.risk_statement or "", limit=260),
                    "evaluation_metrics": [_normalize_text(x, limit=120) for x in item.evaluation_metrics if _normalize_text(x, limit=120)],
                    "timeline": _normalize_text(item.timeline or "", limit=120),
                    "novelty_score": max(0.0, min(1.0, float(item.novelty_score or 0.0))),
                    "feasibility_score": max(0.0, min(1.0, float(item.feasibility_score or 0.0))),
                    "relevance_score": max(0.0, min(1.0, float(item.relevance_score or 0.0))),
                    "generation_mode": "llm_rl" if (optimize_prompt and method == "rl_bandit") else ("llm_optimized" if optimize_prompt else "llm"),
                    "prompt_variant": style,
                    "generation_confidence": max(0.0, min(1.0, float(item.generation_confidence or 0.0))),
                    "optimization_score": opt_score,
                    "source_claim_ids": list(gap.get("source_claim_ids") or []),
                    "source_community_ids": list(gap.get("source_community_ids") or []),
                    "source_paper_ids": list(gap.get("source_paper_ids") or []),
                    "inspiration_adjacent_paper_ids": list(gap.get("inspiration_adjacent_paper_ids") or []),
                    "inspiration_random_paper_ids": list(gap.get("inspiration_random_paper_ids") or []),
                    "inspiration_community_paper_ids": list(gap.get("inspiration_community_paper_ids") or []),
                    "graph_context_summary": graph_context_summary
                    or _normalize_text(json.dumps(gap.get("signals") or {}, ensure_ascii=False), limit=220),
                    "rag_context_snippets": rag_context_snippets
                    or [_normalize_text(str(gap.get("missing_evidence_statement") or ""), limit=220)],
                }
            )

    if not all_items:
        return []

    all_items.sort(
        key=lambda x: (
            float(x.get("optimization_score") or 0.0),
            float(x.get("generation_confidence") or 0.0),
            float(x.get("relevance_score") or 0.0),
        ),
        reverse=True,
    )
    return all_items[: max(1, min(3, int(candidates_per_gap)))]


def generate_candidate_questions(
    gaps: list[dict],
    *,
    domain: str = "default",
    candidates_per_gap: int = 2,
    use_llm: bool = True,
    optimize_prompt: bool = True,
    prompt_optimization_method: str = "rl_bandit",
) -> list[dict]:
    """Generate structured question candidates from gap seeds."""
    per_gap = max(1, min(3, int(candidates_per_gap)))
    out: list[dict] = []

    for idx, gap in enumerate(gaps or [], start=1):
        row = dict(gap or {})
        llm_items: list[dict] = []
        if use_llm:
            llm_items = _llm_candidates_for_gap(
                row,
                domain=str(domain or "default"),
                index=idx,
                candidates_per_gap=per_gap,
                optimize_prompt=bool(optimize_prompt),
                prompt_optimization_method=str(prompt_optimization_method or "rl_bandit"),
            )

        if llm_items:
            out.extend(llm_items)
            continue

        for variant in range(1, per_gap + 1):
            out.append(_template_candidate(row, index=idx, variant=variant))

    # deterministic dedup by normalized question text
    dedup: dict[str, dict] = {}
    for item in out:
        key = _normalize_text(str(item.get("question") or ""), limit=260).lower()
        if not key:
            continue
        prev = dedup.get(key)
        if prev is None:
            dedup[key] = item
            continue
        if float(item.get("generation_confidence") or 0.0) > float(prev.get("generation_confidence") or 0.0):
            dedup[key] = item

    ordered = sorted(
        dedup.values(),
        key=lambda x: (
            float(x.get("optimization_score") or 0.0),
            float(x.get("relevance_score") or 0.0),
            float(x.get("generation_confidence") or 0.0),
            str(x.get("candidate_id") or ""),
        ),
        reverse=True,
    )
    return ordered
