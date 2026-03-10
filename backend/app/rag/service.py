from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI

from app.graph.neo4j_client import Neo4jClient
from app.ingest.paper_meta import load_canonical_meta
from app.rag.evidence_orchestrator import _rrf_fuse, merge_evidence, merge_structured_channels
from app.rag.models import AskQueryPlan, EvidenceBundle
from app.rag.fusion_retrieval import (
    format_fusion_evidence_block,
    fusion_rows_to_structured_hits,
    has_dual_evidence,
    rank_fusion_basics,
)
from app.rag.planner import plan_ask_query, resolve_query_plan
from app.rag.retrieval import latest_run_dir, load_chunks_from_run, lexical_retrieve
from app.rag.structured_retrieval import (
    normalize_structured_rows,
    retrieve_claims,
    retrieve_logic_steps,
    retrieve_propositions,
)
from app.rag.tree_router import route_query
from app.retrieval.pageindex_adapter import PageIndexAdapter
from app.settings import settings
from app.vector.faiss_store import load_faiss

log = logging.getLogger(__name__)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_:+./-]*|\d[\d_./-]*")
_GROUNDING_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？;；])\s+|\n+")
_ZH_RETRIEVAL_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("方法", "做法", "算法", "模型", "框架", "技术路线"), "method methodology approach framework model algorithm pipeline"),
    (("结论", "发现", "结果"), "results findings conclusion key findings"),
    (("证据", "依据", "支撑", "证明", "验证"), "evidence support experimental evidence table figure quantitative result"),
    (("机制", "机理", "原因"), "mechanism explanation causal mechanism"),
    (("实验", "试验", "仿真", "模拟"), "experiment simulation evaluation setup"),
    (("背景", "动机"), "background motivation introduction"),
    (("贡献", "创新"), "contribution novelty main contribution"),
    (("问题", "任务", "目标"), "research question problem task objective"),
    (("比较", "对比", "优缺点"), "comparison baseline ablation advantage limitation"),
)


def _runs_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runs"


def _storage_dir() -> Path:
    p = Path(__file__).resolve().parents[2] / settings.storage_dir
    p.mkdir(parents=True, exist_ok=True)
    return p


def global_faiss_dir() -> Path:
    return _storage_dir() / "faiss"


def latest_faiss_dir() -> Path:
    g = global_faiss_dir()
    if g.exists():
        return g
    latest = _runs_dir() / "LATEST"
    if not latest.exists():
        raise FileNotFoundError("No FAISS index yet. Build one via /tasks/rebuild/faiss or call /ingest/path first.")
    run_id = latest.read_text(encoding="utf-8").strip()
    faiss_dir = _runs_dir() / run_id / "faiss"
    if not faiss_dir.exists():
        raise FileNotFoundError(
            f"FAISS index not found for run {run_id}. Build global index via /tasks/rebuild/faiss or re-run ingest with an embeddings-capable provider."
        )
    return faiss_dir


def _paper_id_from_md_path(md_path: str | None) -> str | None:
    if not md_path:
        return None
    meta = load_canonical_meta(md_path)
    doi = str(meta.get("doi") or "").strip().lower()
    if not doi:
        return None
    return f"doi:{doi}"


def _paper_source_from_md_path(md_path: str | None) -> str | None:
    if not md_path:
        return None
    try:
        path = Path(md_path)
    except Exception:
        return None
    if path.suffix.lower() == ".md":
        if path.parent and path.parent.name:
            return path.parent.name
        if path.stem:
            return path.stem
    if path.name:
        return path.name
    return None


@lru_cache(maxsize=4096)
def _paper_title_from_md_path(md_path: str | None) -> str | None:
    if not md_path:
        return None
    meta = load_canonical_meta(md_path)
    for key in ("title", "paper_title", "title_alt"):
        title = str(meta.get(key) or "").strip()
        if title:
            return title
    return None


def _allowed_paper_sources(scope: dict | None) -> set[str] | None:
    if not scope:
        return None
    mode = str(scope.get("mode") or "all").strip().lower()
    if mode == "all":
        return None
    if mode == "collection":
        cid = str(scope.get("collection_id") or "").strip()
        if not cid:
            return set()
        try:
            with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
                return set(client.list_paper_sources_for_collection(cid))
        except Exception:
            return set()
    if mode == "papers":
        ids = scope.get("paper_ids") or []
        paper_ids = _normalize_scope_paper_refs(ids)
        if not paper_ids:
            return set()
        try:
            with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
                return set(client.list_paper_sources_for_paper_ids(paper_ids))
        except Exception:
            return set()
    return None


def _normalize_scope_paper_refs(values: list[Any] | tuple[Any, ...] | set[Any] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values or []:
        text = str(raw or "").strip()
        if not text:
            continue
        if text.startswith("paper:"):
            text = text[len("paper:"):].strip()
        elif text.startswith("paper_source:"):
            text = text[len("paper_source:"):].strip()
        else:
            match = re.match(r"^(logic|claim):([^:]+):\d+$", text)
            if match:
                text = str(match.group(2) or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _single_scope_paper_context(scope: dict | None) -> dict[str, str] | None:
    if not scope:
        return None
    mode = str(scope.get("mode") or "all").strip().lower()
    if mode != "papers":
        return None
    refs = _normalize_scope_paper_refs(scope.get("paper_ids") or [])
    if len(refs) != 1:
        return None
    paper_ref = refs[0]
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            detail = client.get_paper_detail(paper_ref)
    except Exception:
        return None
    paper = detail.get("paper") if isinstance(detail, dict) else None
    if not isinstance(paper, dict):
        return None
    paper_id = str(paper.get("paper_id") or "").strip()
    paper_source = str(paper.get("paper_source") or "").strip()
    paper_title = str(paper.get("title") or "").strip()
    if not (paper_id or paper_source or paper_title):
        return None
    return {
        "paper_id": paper_id,
        "paper_source": paper_source,
        "paper_title": paper_title,
    }


def _contains_cjk(text: str | None) -> bool:
    return bool(_CJK_RE.search(str(text or "")))


def _dedupe_text_parts(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in parts:
        text = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _sanitize_retrieval_rewrite(text: str | None) -> str:
    raw = str(text or "").replace("```", " ").strip()
    if not raw:
        return ""
    cleaned_lines: list[str] = []
    for line in raw.splitlines():
        item = re.sub(r"^[\s>*`#\-0-9\.\)\(]+", "", line).strip()
        item = re.sub(r"(?i)^(english retrieval rewrite|retrieval rewrite|retrieval query|query)\s*:\s*", "", item)
        item = item.strip(" \"'`")
        if item:
            cleaned_lines.append(item)
    if not cleaned_lines:
        return ""
    merged = " ".join(cleaned_lines[:3])
    return re.sub(r"\s+", " ", merged).strip()[:400]


def _heuristic_retrieval_rewrite(question: str) -> str:
    text = str(question or "").strip()
    if not text:
        return ""
    parts: list[str] = []
    for needles, expansion in _ZH_RETRIEVAL_HINTS:
        if any(needle in text for needle in needles):
            parts.append(expansion)
    ascii_tokens = [
        token
        for token in _ASCII_TOKEN_RE.findall(text)
        if token and len(token) >= 2 and token.casefold() not in {"what", "which", "this", "that", "with", "from"}
    ]
    if ascii_tokens:
        parts.append("keywords " + " ".join(_dedupe_text_parts(ascii_tokens)[:12]))
    return "\n".join(_dedupe_text_parts(parts))


def _llm_retrieval_rewrite(question: str, locale: str | None = None) -> str:
    text = str(question or "").strip()
    if not text or not _contains_cjk(text):
        return ""
    api_key = settings.effective_llm_api_key()
    base_url = settings.effective_llm_base_url()
    if not api_key:
        return ""
    timeout_seconds = max(5, min(20, int(getattr(settings, "llm_timeout_seconds", 60) or 60) // 4 or 12))
    try:
        client = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=settings.llm_model,
            temperature=0,
            timeout=timeout_seconds,
            max_tokens=96,
            max_retries=0,
        )
        response = client.invoke(
            [
                (
                    "system",
                    (
                        "Rewrite scientific questions into a short English retrieval query for an English research corpus. "
                        "Preserve technical nouns, acronyms, formulas, paper IDs, and specific entities. "
                        "Return one concise line only, without commentary."
                    ),
                ),
                (
                    "user",
                    (
                        f"Locale: {_normalize_locale(locale)}\n"
                        "Task: rewrite the question into English search keywords for retrieval.\n"
                        f"Question: {text}"
                    ),
                ),
            ]
        )
    except Exception:
        log.debug("Retrieval rewrite LLM failed; falling back to heuristics", exc_info=True)
        return ""
    return _sanitize_retrieval_rewrite(getattr(response, "content", ""))


def _rewrite_query_for_retrieval(question: str, locale: str | None = None) -> str:
    text = str(question or "").strip()
    if not text:
        return ""
    normalized_locale = _normalize_locale(locale)
    if normalized_locale != "zh-CN" and not _contains_cjk(text):
        return ""
    parts: list[str] = []
    llm_rewrite = _llm_retrieval_rewrite(text, locale=normalized_locale)
    if llm_rewrite:
        parts.append(llm_rewrite)
    heuristic_rewrite = _heuristic_retrieval_rewrite(text)
    if heuristic_rewrite:
        parts.append(heuristic_rewrite)
    return "\n".join(_dedupe_text_parts(parts))


def _build_retrieval_query(
    question: str,
    scope_paper: dict[str, str] | None,
    *,
    locale: str | None = None,
) -> str:
    base = str(question or "").strip()
    parts = [base]
    bilingual_rewrite = _rewrite_query_for_retrieval(base, locale=locale)
    if bilingual_rewrite:
        parts.append(f"English retrieval rewrite: {bilingual_rewrite}")
    if not scope_paper:
        return "\n".join(part for part in parts if part)
    paper_title = str(scope_paper.get("paper_title") or "").strip()
    paper_source = str(scope_paper.get("paper_source") or "").strip()
    paper_id = str(scope_paper.get("paper_id") or "").strip()
    if paper_title:
        parts.append(f"paper title: {paper_title}")
    if paper_source:
        parts.append(f"paper source: {paper_source}")
    if paper_id:
        parts.append(f"paper id: {paper_id}")
    parts.append("focus: abstract introduction method results conclusion contribution evidence")
    return "\n".join(part for part in parts if part)


def _format_scope_paper_context(scope_paper: dict[str, str] | None) -> str:
    if not scope_paper:
        return ""
    lines = ["Scoped Paper:"]
    paper_title = str(scope_paper.get("paper_title") or "").strip()
    paper_source = str(scope_paper.get("paper_source") or "").strip()
    paper_id = str(scope_paper.get("paper_id") or "").strip()
    if paper_title:
        lines.append(f"title={paper_title}")
    if paper_source:
        lines.append(f"source={paper_source}")
    if paper_id:
        lines.append(f"paper_id={paper_id}")
    return "\n".join(lines)


def _normalize_locale(locale: str | None) -> str:
    text = str(locale or "").strip().lower()
    if text == "zh" or text.startswith("zh-"):
        return "zh-CN"
    return "en-US"


def _build_system_prompt(domain_prompt: str | None = None, *, locale: str | None = None) -> str:
    """Build the RAG system prompt with configurable domain context."""
    domain = (domain_prompt or "").strip()
    normalized_locale = _normalize_locale(locale)
    if normalized_locale == "zh-CN":
        if not domain:
            domain = "你是科研知识图谱问答助手。"
        return (
            f"{domain}\n"
            "请严格只依据提供的证据片段、已验证主张和图谱上下文回答。\n"
            "如果证据不足，请明确指出缺少什么信息。\n"
            "引用证据时使用 [E1]、[E2] 这类证据编号。\n"
            "引用已验证主张时使用 [CL:abc123] 这类主张编号。\n"
            "有图谱上下文时，请结合引用关系、逻辑步骤和主张关系进行解释。\n"
            "除用户明确要求外，回答请使用简体中文。"
        )
    if not domain:
        domain = "You are a scientific research assistant."
    return (
        f"{domain}\n"
        "Answer ONLY using the provided evidence snippets, validated claims, and graph context.\n"
        "If evidence is insufficient, say what is missing.\n"
        "Cite evidence by referencing the evidence ids like [E1], [E2].\n"
        "When referencing validated claims, use their claim id like [CL:abc123].\n"
        "When graph context is provided, use it to enrich your answer with "
        "structural relationships (citations, logic steps, claims)."
    )


def _stringify_graph_value(value: Any, *, max_chars: int = 240) -> str:
    """Convert a graph context value to a compact string."""
    if value is None:
        return ""
    if isinstance(value, list):
        text = ", ".join(str(v).strip() for v in value if str(v).strip())
    elif isinstance(value, dict):
        text = ", ".join(
            f"{k}={v}" for k, v in value.items() if str(k).strip() and str(v).strip()
        )
    else:
        text = str(value).strip()
    if not text:
        return ""
    text = " ".join(text.split())
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return text


def _format_graph_context(graph_context: list[dict[str, Any]] | None) -> str:
    """Format graph context entries into a text block for the LLM prompt.

    Caps at 30 entries and 6000 total characters to avoid token overflow.
    Supports list/dict values from Neo4j citation context.
    """
    if not graph_context:
        return ""
    field_order = (
        "paper_source", "doi", "cited_doi", "cited_title", "purpose_labels",
        "total_mentions", "ref_nums", "source_paper", "target_paper",
        "relationship", "purpose", "step_type", "summary",
    )
    max_entries = 30
    max_total_chars = 6000
    header = "Graph Context:"
    remaining = max_total_chars - len(header) - 1
    lines: list[str] = []
    for entry in graph_context[:max_entries]:
        if remaining <= 0:
            break
        if not isinstance(entry, dict):
            continue
        parts = []
        for key in field_order:
            val = _stringify_graph_value(entry.get(key))
            if val:
                parts.append(f"{key}={val}")
        if not parts:
            continue
        line = " | ".join(parts)
        if len(line) > remaining:
            cutoff = max(0, remaining - 3)
            line = (line[:cutoff].rstrip() + "...") if cutoff else ""
        if not line:
            break
        lines.append(line)
        remaining -= len(line) + 1
    if not lines:
        return ""
    return header + "\n" + "\n".join(lines)


def _format_structured_knowledge(knowledge: dict[str, list[dict[str, Any]]] | None) -> str:
    """Format claims and logic steps into a text block for the LLM prompt.

    Each claim includes its claim_id so the LLM can reference it in the answer,
    enabling frontend traceability (e.g. [CL:abc123]).
    """
    if not knowledge:
        return ""
    parts: list[str] = []

    # Logic steps
    steps = knowledge.get("logic_steps") or []
    if steps:
        step_lines = []
        for s in steps[:20]:
            st = str(s.get("step_type") or "").strip()
            summary = str(s.get("summary") or "").strip()
            ps = str(s.get("paper_source") or "").strip()
            if st and summary:
                if len(summary) > 300:
                    summary = summary[:297] + "..."
                step_lines.append(f"  [{ps}] {st}: {summary}")
        if step_lines:
            parts.append("Logic Steps:\n" + "\n".join(step_lines))

    # Claims
    claims = knowledge.get("claims") or []
    if claims:
        claim_lines = []
        for c in claims[:30]:
            cid = str(c.get("claim_id") or "").strip()
            text = str(c.get("text") or "").strip()
            st = str(c.get("step_type") or "").strip()
            conf = c.get("confidence")
            ps = str(c.get("paper_source") or "").strip()
            if cid and text:
                if len(text) > 300:
                    text = text[:297] + "..."
                conf_str = (
                    f" (conf={conf:.2f})"
                    if isinstance(conf, (int, float)) and not isinstance(conf, bool)
                    else ""
                )
                scope = "/".join(part for part in (ps, st) if part)
                scope_str = f" [{scope}]" if scope else ""
                claim_lines.append(f"  [CL:{cid}]{scope_str}{conf_str} {text}")
        if claim_lines:
            parts.append("Validated Claims:\n" + "\n".join(claim_lines))

    if not parts:
        return ""
    return "\n\n".join(parts)


def _stream_chunk_text(chunk: Any) -> str:
    """Extract incremental text from LangChain streaming chunk objects."""
    content = getattr(chunk, "content", chunk)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        for part in content:
            if isinstance(part, str):
                pieces.append(part)
                continue
            if isinstance(part, dict):
                text = str(part.get("text") or "")
                if text:
                    pieces.append(text)
                continue
            text = str(getattr(part, "text", "") or "")
            if text:
                pieces.append(text)
        return "".join(pieces)
    return str(content or "")


def _format_structured_evidence(items: list[dict[str, Any]] | None) -> str:
    if not items:
        return ""
    lines: list[str] = []
    for item in items[:20]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "structured").strip()
        source_id = str(item.get("source_id") or item.get("id") or "").strip()
        text = str(item.get("text") or "").strip()
        if not source_id or not text:
            continue
        lines.append(f"  [{kind}:{source_id}] {text}")
    if not lines:
        return ""
    return "Structured Evidence:\n" + "\n".join(lines)


def _compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _truncate_for_grounding(text: str, max_chars: int = 220) -> str:
    compact = _compact_whitespace(text)
    if len(compact) <= max_chars:
        return compact
    window = compact[:max_chars]
    for punct in (".", "!", "?", "。", "！", "？", ";", "；"):
        pos = window.rfind(punct)
        if pos >= max_chars // 2:
            return window[: pos + 1].strip()
    return window.rstrip(" ,;:") + "..."


def _sentence_candidates(text: str) -> list[str]:
    compact = _compact_whitespace(text)
    if not compact:
        return []
    parts = [_compact_whitespace(part) for part in _GROUNDING_SENTENCE_SPLIT_RE.split(compact) if _compact_whitespace(part)]
    return parts or [compact]


def _tokenize_for_overlap(text: str) -> set[str]:
    compact = _compact_whitespace(text)
    if not compact:
        return set()
    if _CJK_RE.search(compact):
        return {char for char in compact if _CJK_RE.match(char)}
    return {match.group(0).lower() for match in _ASCII_TOKEN_RE.finditer(compact)}


def _sentence_overlap_score(candidate: str, anchor: str) -> tuple[int, int]:
    candidate_tokens = _tokenize_for_overlap(candidate)
    anchor_tokens = _tokenize_for_overlap(anchor)
    if candidate_tokens and anchor_tokens:
        return (len(candidate_tokens & anchor_tokens), -len(candidate))
    if anchor:
        anchor_norm = _compact_whitespace(anchor).lower()
        candidate_norm = _compact_whitespace(candidate).lower()
        if anchor_norm and anchor_norm in candidate_norm:
            return (len(anchor_norm), -len(candidate))
    return (0, -len(candidate))


def _sentence_grounding_quote(quote: str, anchor: str = "", max_chars: int = 220) -> str:
    candidates = _sentence_candidates(quote)
    if not candidates:
        return ""
    if len(candidates) == 1:
        return _truncate_for_grounding(candidates[0], max_chars=max_chars)
    ranked = sorted(
        enumerate(candidates),
        key=lambda item: (_sentence_overlap_score(item[1], anchor), -item[0]),
        reverse=True,
    )
    best = ranked[0][1] if ranked else candidates[0]
    return _truncate_for_grounding(best, max_chars=max_chars)


def _format_grounding(items: list[dict[str, Any]] | None) -> str:
    if not items:
        return ""
    lines: list[str] = []
    for item in items[:24]:
        if not isinstance(item, dict):
            continue
        source_kind = str(item.get("source_kind") or "structured").strip()
        source_id = str(item.get("source_id") or "").strip()
        quote = _sentence_grounding_quote(str(item.get("quote") or "").strip(), str(item.get("anchor_text") or "").strip())
        if not source_id or not quote:
            continue
        location = (
            str(item.get("chunk_id") or "").strip()
            or str(item.get("chapter_id") or "").strip()
            or str(item.get("paper_source") or "").strip()
            or "unknown"
        )
        lines.append(f"  [{source_kind}:{source_id}] @{location} {quote}")
    if not lines:
        return ""
    return "Grounding:\n" + "\n".join(lines)


def _query_plan_value(question: str, query_plan: AskQueryPlan | dict[str, Any] | None) -> AskQueryPlan:
    if isinstance(query_plan, AskQueryPlan):
        return query_plan
    return resolve_query_plan(question, query_plan if isinstance(query_plan, dict) else None)


def _plan_text(plan: AskQueryPlan, field_name: str, *, fallback: str) -> str:
    raw = getattr(plan, field_name, None)
    text = str(raw or "").strip()
    return text or str(fallback or "").strip() or "question"


def _structured_channel_limits(plan_name: str, want: int) -> dict[str, int]:
    base = max(2, want + 1)
    boosted = max(base + 1, want * 2)
    limits = {
        "logic_step": base,
        "claim": base,
        "proposition": base,
        "textbook": base,
    }
    if plan_name == "paper_first_then_textbook":
        limits["logic_step"] = boosted
        limits["claim"] = boosted
    elif plan_name == "textbook_first_then_paper":
        limits["proposition"] = boosted
        limits["textbook"] = boosted
    elif plan_name == "claim_first":
        limits["claim"] = boosted
        limits["logic_step"] = max(base, want + 2)
    elif plan_name == "proposition_first":
        limits["proposition"] = boosted
        limits["textbook"] = max(base, want + 2)
    elif plan_name == "hybrid_parallel":
        limits = {key: max(base, want + 2) for key in limits}
    return limits


def _attach_paper_metadata(
    rows: list[dict[str, Any]] | None,
    evidence: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    paper_id_by_source: dict[str, str] = {}
    for item in evidence or []:
        paper_source = str(item.get("paper_source") or "").strip()
        paper_id = str(item.get("paper_id") or "").strip()
        if paper_source and paper_id and paper_source not in paper_id_by_source:
            paper_id_by_source[paper_source] = paper_id

    hydrated: list[dict[str, Any]] = []
    for row in rows:
        normalized_rows = normalize_structured_rows([row])
        if not normalized_rows:
            continue
        item = dict(normalized_rows[0])
        if isinstance(row, dict):
            for key, value in row.items():
                if key not in item:
                    item[key] = value
        paper_source = str(item.get("paper_source") or "").strip()
        if paper_source and not str(item.get("paper_id") or "").strip():
            paper_id = paper_id_by_source.get(paper_source)
            if paper_id:
                item["paper_id"] = paper_id
        hydrated.append(item)
    return hydrated


def _is_textbook_origin_proposition(row: dict[str, Any]) -> bool:
    source_kind = str(row.get("source_kind") or "").strip().lower()
    return source_kind == "textbook_entity" or bool(
        str(row.get("textbook_id") or "").strip() or str(row.get("chapter_id") or "").strip()
    )


def _filter_scoped_proposition_hits(
    rows: list[dict[str, Any]] | None,
    allowed_sources: set[str] | None,
) -> list[dict[str, Any]]:
    if not rows or allowed_sources is None:
        return list(rows or [])
    allowed = {str(source).strip() for source in allowed_sources if str(source).strip()}
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        paper_source = str(row.get("paper_source") or "").strip()
        if paper_source:
            if paper_source in allowed:
                filtered.append(row)
            continue
        if _is_textbook_origin_proposition(row):
            filtered.append(row)
    return filtered


def _normalize_structured_rows_preserving_extras(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        normalized_rows = normalize_structured_rows([row])
        if not normalized_rows:
            continue
        item = dict(normalized_rows[0])
        if isinstance(row, dict):
            for key, value in row.items():
                if key not in item:
                    item[key] = value
        out.append(item)
    return out


def _structured_row_by_source_id(rows: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        source_id = str(row.get("source_id") or "").strip()
        if source_id and source_id not in out:
            out[source_id] = row
    return out


def _paper_identity_by_source(evidence: list[dict[str, Any]] | None) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in evidence or []:
        if not isinstance(row, dict):
            continue
        paper_source = str(row.get("paper_source") or "").strip()
        paper_id = str(row.get("paper_id") or "").strip()
        if not paper_source:
            continue
        item = out.setdefault(paper_source, {})
        if paper_id and not item.get("paper_id"):
            item["paper_id"] = paper_id
    return out


def _hydrate_grounding_row(
    row: dict[str, Any],
    structured_row: dict[str, Any] | None,
    paper_identity: dict[str, dict[str, str]],
) -> dict[str, Any]:
    item = dict(row)
    structured_row = structured_row or {}
    paper_source = str(item.get("paper_source") or structured_row.get("paper_source") or "").strip()
    if not paper_source:
        paper_source = str(structured_row.get("paper_source") or "").strip()
    if paper_source:
        item["paper_source"] = paper_source
        paper_meta = paper_identity.get(paper_source) or {}
        paper_id = str(item.get("paper_id") or structured_row.get("paper_id") or paper_meta.get("paper_id") or "").strip()
        if paper_id:
            item["paper_id"] = paper_id
    elif structured_row.get("paper_id"):
        item["paper_id"] = structured_row.get("paper_id")

    for key in (
        "chunk_id",
        "md_path",
        "start_line",
        "end_line",
        "textbook_id",
        "chapter_id",
        "evidence_event_id",
        "evidence_event_type",
    ):
        if item.get(key) in (None, "", []):
            value = structured_row.get(key)
            if value not in (None, "", []):
                item[key] = value
    anchor_text = str(structured_row.get("text") or structured_row.get("summary") or structured_row.get("evidence_quote") or "").strip()
    if anchor_text:
        item["anchor_text"] = anchor_text
    item["quote"] = _sentence_grounding_quote(str(item.get("quote") or "").strip(), anchor_text)
    return item


def _fallback_grounding_rows(
    structured_rows: list[dict[str, Any]] | None,
    paper_identity: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in structured_rows or []:
        if not isinstance(row, dict):
            continue
        source_id = str(row.get("source_id") or "").strip()
        quote = str(row.get("evidence_quote") or "").strip()
        if not source_id or not quote:
            continue
        source_kind = str(row.get("kind") or row.get("source_kind") or "").strip() or "structured"
        item = {
            "source_kind": source_kind,
            "source_id": source_id,
            "quote": _sentence_grounding_quote(quote, str(row.get("text") or "").strip()),
            "paper_source": str(row.get("paper_source") or "").strip() or None,
            "paper_id": str(row.get("paper_id") or "").strip() or None,
            "chunk_id": str(row.get("source_chunk_id") or "").strip() or None,
            "md_path": None,
            "start_line": None,
            "end_line": None,
            "textbook_id": str(row.get("textbook_id") or "").strip() or None,
            "chapter_id": str(row.get("chapter_id") or row.get("source_chapter_id") or "").strip() or None,
            "evidence_event_id": str(row.get("evidence_event_id") or "").strip() or None,
            "evidence_event_type": str(row.get("evidence_event_type") or "").strip() or None,
            "anchor_text": str(row.get("text") or "").strip() or None,
        }
        if item["paper_source"]:
            meta = paper_identity.get(str(item["paper_source"])) or {}
            if meta.get("paper_id") and not item["paper_id"]:
                item["paper_id"] = meta["paper_id"]
        out.append(item)
    return out


def _dedupe_grounding_rows(rows: list[dict[str, Any]] | None, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        source_kind = str(row.get("source_kind") or "").strip()
        source_id = str(row.get("source_id") or "").strip()
        quote = str(row.get("quote") or "").strip()
        if not source_kind or not source_id or not quote:
            continue
        key = (source_kind, source_id, quote)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _normalize_grounding_seed_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        source_id = str(row.get("source_id") or row.get("id") or "").strip()
        kind = str(row.get("kind") or row.get("source_kind") or "").strip() or "structured"
        if not source_id:
            continue
        item = dict(row)
        item["source_id"] = source_id
        item["kind"] = kind
        item["id"] = str(row.get("id") or source_id).strip() or source_id
        item["text"] = str(row.get("text") or row.get("summary") or row.get("evidence_quote") or "").strip()
        out.append(item)
    return out


def retrieve_structured_evidence(
    *,
    question: str,
    query_plan: AskQueryPlan | dict[str, Any] | None,
    evidence: list[dict[str, Any]] | None,
    allowed_sources: set[str] | None,
    k: int,
    fusion_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    plan = _query_plan_value(question, query_plan)
    plan_name = str(getattr(plan.retrieval_plan, "value", plan.retrieval_plan) or "").strip()
    want = max(1, int(k))
    limits = _structured_channel_limits(plan_name, want)

    paper_query = _plan_text(plan, "paper_query", fallback=plan.main_query)
    textbook_query = _plan_text(plan, "textbook_query", fallback=plan.main_query)
    proposition_query = _plan_text(plan, "proposition_query", fallback=textbook_query or plan.main_query)

    logic_hits = _attach_paper_metadata(
        retrieve_logic_steps(paper_query, limits["logic_step"], allowed_sources=allowed_sources),
        evidence,
    )
    claim_hits = _attach_paper_metadata(
        retrieve_claims(paper_query, limits["claim"], allowed_sources=allowed_sources),
        evidence,
    )

    proposition_hits = _attach_paper_metadata(
        _filter_scoped_proposition_hits(
            retrieve_propositions(proposition_query, limits["proposition"], allowed_sources=None),
            allowed_sources,
        ),
        evidence,
    )

    ranked_textbook_rows = rank_fusion_basics(textbook_query, fusion_rows or [], k=limits["textbook"])
    textbook_hits = _attach_paper_metadata(fusion_rows_to_structured_hits(ranked_textbook_rows), evidence)

    channel_order = {
        "textbook_first_then_paper": ["textbook", "proposition", "claim", "logic_step"],
        "claim_first": ["claim", "logic_step", "proposition", "textbook"],
        "proposition_first": ["proposition", "textbook", "claim", "logic_step"],
        "hybrid_parallel": ["claim", "proposition", "logic_step", "textbook"],
        "paper_first_then_textbook": ["claim", "logic_step", "textbook", "proposition"],
    }.get(plan_name, ["claim", "logic_step", "textbook", "proposition"])

    channel_map = {
        "logic_step": logic_hits,
        "claim": claim_hits,
        "proposition": proposition_hits,
        "textbook": textbook_hits,
    }
    merged = merge_structured_channels(
        channels=[(name, channel_map.get(name, [])) for name in channel_order],
        k=want,
    )
    return _normalize_structured_rows_preserving_extras(merged)


def ground_structured_evidence(*args, **kwargs) -> list[dict[str, Any]]:  # noqa: ANN002, ANN003
    structured_rows = _normalize_grounding_seed_rows(kwargs.get("structured_evidence") or [])
    if not structured_rows:
        return []

    limit = max(1, min(200, int(kwargs.get("k") or len(structured_rows) or 1) * 3))
    structured_index = _structured_row_by_source_id(structured_rows)
    paper_identity = _paper_identity_by_source(kwargs.get("evidence") or [])

    graph_rows: list[dict[str, Any]] = []
    graph_targets = [
        {"kind": str(row.get("kind") or "").strip(), "source_id": str(row.get("source_id") or "").strip()}
        for row in structured_rows
        if str(row.get("kind") or "").strip() in {"claim", "logic_step", "proposition"}
        and str(row.get("source_id") or "").strip()
    ]
    if graph_targets:
        try:
            with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
                graph_rows = list(client.get_grounding_rows_for_structured_ids(graph_targets, limit=limit) or [])
        except Exception:
            log.debug("Structured grounding lookup failed; using fallback-only grounding", exc_info=True)
            graph_rows = []

    hydrated = [
        _hydrate_grounding_row(row, structured_index.get(str(row.get("source_id") or "").strip()), paper_identity)
        for row in graph_rows
    ]
    fallback_rows = _fallback_grounding_rows(structured_rows, paper_identity)
    return _dedupe_grounding_rows([*hydrated, *fallback_rows], limit=limit)


def _prepare_ask_v2_context(
    question: str,
    k: int = 8,
    scope: dict | None = None,
    *,
    locale: str | None = None,
    domain_prompt: str | None = None,
) -> dict[str, Any]:
    normalized_locale = _normalize_locale(locale)
    api_key = settings.effective_llm_api_key()
    base_url = settings.effective_llm_base_url()
    if not api_key:
        raise RuntimeError("LLM API key is required for /rag/ask (set DEEPSEEK_API_KEY or LLM_API_KEY)")

    allowed_sources = _allowed_paper_sources(scope)
    scope_paper = _single_scope_paper_context(scope)
    raw_query_plan = plan_ask_query(question, scope=scope, locale=normalized_locale)
    query_plan = (
        raw_query_plan
        if isinstance(raw_query_plan, AskQueryPlan)
        else resolve_query_plan(question, raw_query_plan)
    )
    plan_name = str(getattr(query_plan.retrieval_plan, "value", query_plan.retrieval_plan) or "").strip()
    paper_query = _plan_text(query_plan, "paper_query", fallback=query_plan.main_query)
    textbook_query = _plan_text(query_plan, "textbook_query", fallback=query_plan.main_query)
    seed_query = textbook_query if plan_name == "textbook_first_then_paper" else paper_query
    retrieval_query = _build_retrieval_query(seed_query, scope_paper, locale=normalized_locale)
    want = max(1, int(k))
    oversample = min(100, max(want, want * 5))
    if plan_name == "claim_first":
        oversample = min(100, max(oversample, want * 6))
    elif plan_name == "proposition_first":
        oversample = min(100, max(oversample, want * 4))
    route = route_query(
        retrieval_query,
        pageindex_enabled=bool(settings.pageindex_enabled),
    )
    pageindex_results: list[dict[str, Any]] = []

    # FAISS retrieval
    faiss_results: list[dict[str, Any]] = []
    try:
        store = load_faiss(str(latest_faiss_dir()))
        docs_and_scores = store.similarity_search_with_score(retrieval_query, k=oversample)
        for doc, score in docs_and_scores:
            md = doc.metadata or {}
            snippet = (doc.page_content or "").strip()[:1200]
            md_path = str(md.get("md_path") or "").strip() or None
            paper_source = str(md.get("paper_source") or "").strip() or _paper_source_from_md_path(md_path)
            paper_title = str(md.get("paper_title") or "").strip() or _paper_title_from_md_path(md_path)
            if allowed_sources is not None:
                ps = paper_source or ""
                if not ps or ps not in allowed_sources:
                    continue
            faiss_results.append({
                "chunk_id": md.get("chunk_id"),
                "score": float(score),
                "paper_source": paper_source,
                "paper_title": paper_title,
                "md_path": md.get("md_path"),
                "start_line": md.get("start_line"),
                "end_line": md.get("end_line"),
                "section": md.get("section"),
                "kind": md.get("kind"),
                "snippet": snippet,
                "mode": "faiss",
            })
    except FileNotFoundError as e:
        raise FileNotFoundError("FAISS index not found. Please run full rebuild first.") from e
    except Exception as e:
        raise RuntimeError(f"FAISS retrieval failed: {e}") from e

    if route.get("mode") == "pageindex":
        try:
            adapter = PageIndexAdapter()
            raw_pageindex = adapter.retrieve(
                retrieval_query,
                k=oversample,
                allowed_sources=allowed_sources,
            )
            for row in raw_pageindex:
                item = dict(row)
                md_path = str(item.get("md_path") or "").strip() or None
                paper_source = str(item.get("paper_source") or "").strip() or _paper_source_from_md_path(md_path)
                paper_title = str(item.get("paper_title") or "").strip() or _paper_title_from_md_path(md_path)
                if allowed_sources is not None and (not paper_source or paper_source not in allowed_sources):
                    continue
                item["paper_source"] = paper_source
                item["paper_title"] = paper_title
                pageindex_results.append(item)
        except Exception:
            # Hard fallback guarantee: any adapter issue keeps legacy hybrid path.
            log.debug("PageIndex adapter failed; fallback to FAISS+lexical", exc_info=True)
            pageindex_results = []

    # Lexical retrieval (BM25-like)
    lexical_results: list[dict[str, Any]] = []
    try:
        run_dir = latest_run_dir(_runs_dir())
        chunks = load_chunks_from_run(run_dir)
        lex_hits = lexical_retrieve(retrieval_query, chunks, k=oversample)
        for hit in lex_hits:
            md_path = str(hit.md_path or "").strip() or None
            paper_source = str(hit.paper_source or "").strip() or _paper_source_from_md_path(md_path)
            paper_title = _paper_title_from_md_path(md_path)
            if allowed_sources is not None:
                if not paper_source or paper_source not in allowed_sources:
                    continue
            lexical_results.append({
                "chunk_id": hit.chunk_id,
                "score": hit.score,
                "paper_source": paper_source,
                "paper_title": paper_title,
                "md_path": hit.md_path,
                "start_line": hit.start_line,
                "end_line": hit.end_line,
                "section": hit.section,
                "kind": hit.kind,
                "snippet": hit.snippet,
                "mode": "lexical",
            })
    except Exception:
        log.debug("Lexical retrieval unavailable, falling back to FAISS-only")

    # RRF fusion
    primary_results = pageindex_results if pageindex_results else faiss_results
    fused = merge_evidence(
        faiss=primary_results,
        lexical=lexical_results,
        k=want,
    )

    # Build final evidence list
    evidence: list[dict[str, Any]] = []
    context_lines: list[str] = []
    for item in fused:
        md_path = str(item.get("md_path") or "").strip() or None
        if not str(item.get("paper_source") or "").strip():
            item["paper_source"] = _paper_source_from_md_path(md_path)
        if not str(item.get("paper_title") or "").strip():
            item["paper_title"] = _paper_title_from_md_path(md_path)
        paper_id = _paper_id_from_md_path(md_path)
        item["rank"] = len(evidence) + 1
        item["paper_id"] = paper_id
        evidence.append(item)
        paper_ref = (
            str(item.get("paper_title") or "").strip()
            or str(item.get("paper_source") or "").strip()
            or str(item.get("paper_id") or "").strip()
            or "paper"
        )
        context_lines.append(
            f"[E{len(evidence)}] {paper_ref} "
            f"{item.get('md_path')}:{item.get('start_line')}-{item.get('end_line')}\n"
            f"{item.get('snippet', '')}"
        )

    if pageindex_results and lexical_results:
        retrieval_mode = "pageindex_hybrid"
    elif pageindex_results:
        retrieval_mode = "pageindex"
    elif lexical_results:
        retrieval_mode = "hybrid"
    else:
        retrieval_mode = "faiss"

    # Hybrid graph context + structured knowledge
    graph_context = None
    structured_knowledge = None
    fusion_rows: list[dict[str, Any]] = []
    fusion_evidence: list[dict[str, Any]] = []
    structured_evidence: list[dict[str, Any]] = []
    grounding: list[dict[str, Any]] = []
    if evidence:
        paper_sources = list({e["paper_source"] for e in evidence if e.get("paper_source")})
        if paper_sources:
            try:
                with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
                    try:
                        graph_context = client.get_citation_context_by_paper_source(paper_sources, limit=50)
                    except Exception:
                        graph_context = None
                    try:
                        structured_knowledge = client.get_structured_knowledge_for_papers(paper_sources)
                    except Exception:
                        structured_knowledge = None
                    try:
                        fusion_rows = client.list_fusion_basics_by_paper_sources(paper_sources, limit=200)
                        fusion_query = textbook_query if plan_name in {
                            "textbook_first_then_paper",
                            "proposition_first",
                            "hybrid_parallel",
                        } else retrieval_query
                        fusion_evidence = rank_fusion_basics(fusion_query, fusion_rows, k=min(12, max(4, want)))
                    except Exception:
                        fusion_rows = []
                        fusion_evidence = []
            except Exception:
                graph_context = None
                structured_knowledge = None
                fusion_rows = []
                fusion_evidence = []
    try:
        structured_evidence = list(
            retrieve_structured_evidence(
                question=question,
                query_plan=query_plan,
                evidence=evidence,
                allowed_sources=allowed_sources,
                k=want,
                fusion_rows=fusion_rows,
            )
            or []
        )
    except Exception:
        structured_evidence = []
    try:
        grounding = list(
            ground_structured_evidence(
                structured_evidence=structured_evidence,
                evidence=evidence,
                k=want,
            )
            or []
        )
    except Exception:
        grounding = []

    if allowed_sources is not None and len(evidence) < min(2, want) and not structured_evidence:
        bundle = EvidenceBundle(
            evidence=evidence,
            query_plan=query_plan,
            structured_evidence=[],
            grounding=grounding,
            retrieval_mode=retrieval_mode,
            graph_context=graph_context,
            structured_knowledge=structured_knowledge,
            insufficient_scope_evidence=True,
            message=(
                "当前范围内证据不足，请扩大范围或细化问题。"
                if normalized_locale == "zh-CN"
                else "Insufficient evidence in current scope. Broaden scope or refine the question."
            ),
        )
        return {"early_response": {"answer": "", **bundle.model_dump()}}

    system = _build_system_prompt(domain_prompt, locale=normalized_locale)
    graph_block = _format_graph_context(graph_context)
    knowledge_block = _format_structured_knowledge(structured_knowledge)
    structured_block = _format_structured_evidence(structured_evidence)
    grounding_block = _format_grounding(grounding)
    evidence_block = "Evidence:\n" + "\n\n".join(context_lines)
    textbook_block = format_fusion_evidence_block(fusion_evidence) if fusion_evidence else ""
    user_parts = [f"Question:\n{question}"]
    scope_paper_block = _format_scope_paper_context(scope_paper)
    if scope_paper_block:
        user_parts.insert(1, scope_paper_block)
    if plan_name == "textbook_first_then_paper":
        if structured_block:
            user_parts.append(structured_block)
        if grounding_block:
            user_parts.append(grounding_block)
        if textbook_block:
            user_parts.append(textbook_block)
        user_parts.append(evidence_block)
    else:
        user_parts.append(evidence_block)
        if structured_block:
            user_parts.append(structured_block)
        if grounding_block:
            user_parts.append(grounding_block)
        if textbook_block:
            user_parts.append(textbook_block)
    if knowledge_block:
        user_parts.append(knowledge_block)
    if graph_block:
        user_parts.append(graph_block)
    user = "\n\n".join(user_parts)

    bundle = EvidenceBundle(
        evidence=evidence,
        fusion_evidence=fusion_evidence,
        query_plan=query_plan,
        structured_evidence=structured_evidence,
        grounding=grounding,
        dual_evidence_coverage=has_dual_evidence(
            paper_evidence_count=len(evidence),
            textbook_evidence_count=len(fusion_evidence),
        ),
        retrieval_mode=retrieval_mode,
        graph_context=graph_context,
        structured_knowledge=structured_knowledge,
        insufficient_scope_evidence=False,
        message=None,
    )
    return {
        "api_key": api_key,
        "base_url": base_url,
        "system": system,
        "user": user,
        "bundle": bundle,
    }


def _build_rag_llm(api_key: str, base_url: str) -> ChatOpenAI:
    rag_timeout = max(10, min(180, int(settings.rag_llm_timeout_seconds)))
    rag_max_tokens = max(128, min(2048, int(settings.rag_llm_max_tokens)))
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=settings.llm_model,
        temperature=0,
        timeout=rag_timeout,
        max_tokens=rag_max_tokens,
        max_retries=0,
    )


def ask_v2(
    question: str,
    k: int = 8,
    scope: dict | None = None,
    *,
    locale: str | None = None,
    domain_prompt: str | None = None,
) -> dict:
    """Answer a question using hybrid retrieval (FAISS + lexical) with graph context."""
    ctx = _prepare_ask_v2_context(question, k=k, scope=scope, locale=locale, domain_prompt=domain_prompt)
    early = ctx.get("early_response")
    if early:
        return dict(early)

    llm = _build_rag_llm(str(ctx["api_key"]), str(ctx["base_url"]))
    msg = llm.invoke([("system", str(ctx["system"])), ("user", str(ctx["user"]))])
    bundle: EvidenceBundle = ctx["bundle"]
    return {"answer": str(msg.content or ""), **bundle.model_dump()}


def ask_v2_stream(
    question: str,
    k: int = 8,
    scope: dict | None = None,
    *,
    locale: str | None = None,
    domain_prompt: str | None = None,
):
    """Stream answer deltas with final structured payload."""
    ctx = _prepare_ask_v2_context(question, k=k, scope=scope, locale=locale, domain_prompt=domain_prompt)
    early = ctx.get("early_response")
    if early:
        yield "done", dict(early)
        return

    llm = _build_rag_llm(str(ctx["api_key"]), str(ctx["base_url"]))
    answer_parts: list[str] = []
    try:
        for chunk in llm.stream([("system", str(ctx["system"])), ("user", str(ctx["user"]))]):
            delta = _stream_chunk_text(chunk)
            if not delta:
                continue
            answer_parts.append(delta)
            yield "delta", {"delta": delta}
    except Exception as exc:
        yield "error", {"error": str(exc)}
        return

    bundle: EvidenceBundle = ctx["bundle"]
    yield "done", {"answer": "".join(answer_parts), **bundle.model_dump()}
