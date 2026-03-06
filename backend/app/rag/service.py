from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI

from app.graph.neo4j_client import Neo4jClient
from app.ingest.paper_meta import load_canonical_meta
from app.rag.evidence_orchestrator import _rrf_fuse, merge_evidence
from app.rag.models import EvidenceBundle
from app.rag.retrieval import latest_run_dir, load_chunks_from_run, lexical_retrieve
from app.rag.tree_router import route_query
from app.retrieval.pageindex_adapter import PageIndexAdapter
from app.settings import settings
from app.vector.faiss_store import load_faiss

log = logging.getLogger(__name__)


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
        paper_ids = [str(x).strip() for x in ids if str(x).strip()]
        if not paper_ids:
            return set()
        try:
            with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
                return set(client.list_paper_sources_for_paper_ids(paper_ids))
        except Exception:
            return set()
    return None


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
    want = max(1, int(k))
    oversample = min(100, max(want, want * 5))
    route = route_query(
        question,
        pageindex_enabled=bool(settings.pageindex_enabled),
    )
    pageindex_results: list[dict[str, Any]] = []

    # FAISS retrieval
    faiss_results: list[dict[str, Any]] = []
    try:
        store = load_faiss(str(latest_faiss_dir()))
        docs_and_scores = store.similarity_search_with_score(question, k=oversample)
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
                question,
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
        lex_hits = lexical_retrieve(question, chunks, k=oversample)
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

    if allowed_sources is not None and len(evidence) < min(2, want):
        bundle = EvidenceBundle(
            evidence=evidence,
            retrieval_mode=retrieval_mode,
            graph_context=None,
            structured_knowledge=None,
            insufficient_scope_evidence=True,
            message=(
                "当前范围内证据不足，请扩大范围或细化问题。"
                if normalized_locale == "zh-CN"
                else "Insufficient evidence in current scope. Broaden scope or refine the question."
            ),
        )
        return {"early_response": {"answer": "", **bundle.model_dump()}}

    # Hybrid graph context + structured knowledge
    graph_context = None
    structured_knowledge = None
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
            except Exception:
                graph_context = None
                structured_knowledge = None

    system = _build_system_prompt(domain_prompt, locale=normalized_locale)
    graph_block = _format_graph_context(graph_context)
    knowledge_block = _format_structured_knowledge(structured_knowledge)
    user_parts = [f"Question:\n{question}", "Evidence:\n" + "\n\n".join(context_lines)]
    if knowledge_block:
        user_parts.append(knowledge_block)
    if graph_block:
        user_parts.append(graph_block)
    user = "\n\n".join(user_parts)

    bundle = EvidenceBundle(
        evidence=evidence,
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
