from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.graph.neo4j_client import Neo4jClient
from app.settings import settings
from app.vector.faiss_store import load_faiss

log = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[A-Za-z0-9_:+./-]+|[\u4e00-\u9fff]+")
_CORPUS_KIND = {
    "logic_steps": "logic_step",
    "claims": "claim",
    "propositions": "proposition",
}


def _tokens(text: str) -> list[str]:
    return [tok.casefold() for tok in _TOKEN_RE.findall(str(text or "")) if tok.strip()]


def _score_text(query: str, text: str) -> float:
    query_tokens = _tokens(query)
    text_tokens = _tokens(text)
    if not query_tokens or not text_tokens:
        return 0.0
    text_set = set(text_tokens)
    overlap = sum(1 for token in query_tokens if token in text_set)
    return overlap / max(len(set(query_tokens)), 1)


def _score_row(query: str, row: dict[str, Any]) -> float:
    candidates = [
        str(row.get("text") or ""),
        str(row.get("quote") or ""),
        str(row.get("evidence_quote") or ""),
    ]
    return max((_score_text(query, candidate) for candidate in candidates), default=0.0)


def normalize_structured_rows(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").strip() or "structured"
        source_id = str(row.get("source_id") or row.get("id") or "").strip()
        text = str(row.get("text") or "").strip()
        if not source_id or not text:
            continue
        normalized = dict(row)
        normalized["kind"] = kind
        normalized["source_id"] = source_id
        normalized["id"] = str(row.get("id") or source_id).strip() or source_id
        normalized["text"] = text
        if kind == "proposition":
            normalized["proposition_id"] = str(row.get("proposition_id") or source_id).strip() or source_id
        if "source_kind" in row:
            normalized["source_kind"] = str(row.get("source_kind") or "").strip() or None
        if "source_ref_id" in row:
            normalized["source_ref_id"] = str(row.get("source_ref_id") or "").strip() or None
        elif "source_id" in row and kind == "proposition":
            normalized["source_ref_id"] = str(row.get("source_id") or "").strip() or None
        if "quote" in row:
            normalized["quote"] = str(row.get("quote") or "").strip() or None
        if "evidence_quote" in row:
            normalized["evidence_quote"] = str(row.get("evidence_quote") or "").strip() or None
        if "paper_source" in row:
            normalized["paper_source"] = str(row.get("paper_source") or "").strip() or None
        if "paper_id" in row:
            normalized["paper_id"] = str(row.get("paper_id") or "").strip() or None
        if "chunk_id" in row:
            normalized["chunk_id"] = str(row.get("chunk_id") or "").strip() or None
        if "chapter_id" in row:
            normalized["chapter_id"] = str(row.get("chapter_id") or "").strip() or None
        if "textbook_id" in row:
            normalized["textbook_id"] = str(row.get("textbook_id") or "").strip() or None
        if "evidence_event_id" in row:
            normalized["evidence_event_id"] = str(row.get("evidence_event_id") or "").strip() or None
        if "evidence_event_type" in row:
            normalized["evidence_event_type"] = str(row.get("evidence_event_type") or "").strip() or None
        if "proposition_id" in row and kind != "proposition":
            normalized["proposition_id"] = str(row.get("proposition_id") or "").strip() or None
        if "start_line" in row:
            normalized["start_line"] = row.get("start_line")
        if "end_line" in row:
            normalized["end_line"] = row.get("end_line")
        if "score" in row:
            try:
                normalized["score"] = float(row.get("score"))
            except Exception:
                normalized["score"] = 0.0
        out.append(normalized)
    return out


def _load_corpus_rows(corpus: str) -> list[dict[str, Any]]:
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            if corpus == "logic_steps":
                return client.list_logic_step_structured_rows()
            if corpus == "claims":
                return client.list_claim_structured_rows()
            if corpus == "propositions":
                return client.list_proposition_structured_rows()
    except Exception:
        return []
    return []


def _storage_dir() -> Path:
    path = Path(__file__).resolve().parents[2] / settings.storage_dir
    path.mkdir(parents=True, exist_ok=True)
    return path


def _runs_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "runs"


def _corpus_faiss_dir(corpus: str) -> str:
    corpus_name = str(corpus or "").strip()
    global_root = _storage_dir() / "faiss"
    global_corpus = global_root / corpus_name
    if global_corpus.exists():
        return str(global_corpus)

    run_corpus: Path | None = None
    latest = _runs_dir() / "LATEST"
    if latest.exists():
        run_id = latest.read_text(encoding="utf-8").strip()
        if run_id:
            run_corpus = _runs_dir() / run_id / "faiss" / corpus_name
            if run_corpus.exists():
                return str(run_corpus)

    if global_root.exists():
        return str(global_corpus)
    if run_corpus is not None:
        return str(run_corpus)
    return str(global_corpus)


def _normalize_faiss_hit(corpus: str, doc: Any, score: float) -> dict[str, Any]:
    metadata = dict(getattr(doc, "metadata", {}) or {})
    row = dict(metadata)
    row["kind"] = str(metadata.get("kind") or _CORPUS_KIND.get(corpus) or "structured")
    row["source_id"] = str(metadata.get("source_id") or metadata.get("id") or "").strip()
    row["id"] = str(metadata.get("id") or row["source_id"]).strip() or row["source_id"]
    row["text"] = str(getattr(doc, "page_content", "") or metadata.get("text") or "").strip()
    row["score"] = float(score)
    return row


def _search_via_faiss(corpus: str, query: str, k: int) -> list[dict[str, Any]]:
    store = load_faiss(_corpus_faiss_dir(corpus))
    docs_and_scores = store.similarity_search_with_score(query, k=max(1, int(k)))
    return [
        _normalize_faiss_hit(corpus, doc, float(score))
        for doc, score in docs_and_scores
    ]


def _sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda item: (
            -float(item.get("score") or 0.0),
            str(item.get("paper_source") or ""),
            str(item.get("source_id") or item.get("id") or ""),
        ),
    )


def _search_corpus(corpus: str, query: str, k: int, allowed_sources=None) -> list[dict[str, Any]]:
    allowed = {str(x).strip() for x in (allowed_sources or set()) if str(x).strip()} if allowed_sources else None
    try:
        rows = normalize_structured_rows(_search_via_faiss(corpus, query, k))
    except Exception as exc:
        if not isinstance(exc, FileNotFoundError):
            log.debug("Structured FAISS retrieval failed for corpus=%s; falling back to lexical rows", corpus, exc_info=True)
        rows = normalize_structured_rows(_load_corpus_rows(corpus))
        for row in rows:
            base_score = row.get("score")
            if not isinstance(base_score, (int, float)):
                row["score"] = _score_row(query, row)

    ranked: list[dict[str, Any]] = []
    for row in rows:
        paper_source = str(row.get("paper_source") or "").strip()
        if allowed is not None and paper_source not in allowed:
            continue
        ranked.append(dict(row))

    return _sort_rows(ranked)[: max(1, int(k))]


def retrieve_logic_steps(query: str, k: int, allowed_sources: set[str] | None = None) -> list[dict[str, Any]]:
    return normalize_structured_rows(_search_corpus("logic_steps", query, k, allowed_sources=allowed_sources))


def retrieve_claims(query: str, k: int, allowed_sources: set[str] | None = None) -> list[dict[str, Any]]:
    return normalize_structured_rows(_search_corpus("claims", query, k, allowed_sources=allowed_sources))


def retrieve_propositions(query: str, k: int, allowed_sources: set[str] | None = None) -> list[dict[str, Any]]:
    return normalize_structured_rows(_search_corpus("propositions", query, k, allowed_sources=allowed_sources))


def _hit_key(row: dict[str, Any]) -> tuple[str, str]:
    kind = str(row.get("kind") or "").strip() or "structured"
    ident = (
        str(row.get("source_id") or "").strip()
        or str(row.get("id") or "").strip()
        or str(row.get("chunk_id") or "").strip()
    )
    return kind, ident


def _sorted_hits(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return _sort_rows(normalize_structured_rows(rows))


def fuse_retrieval_channels(
    *,
    retrieval_plan: str,
    question: str,
    chunk_hits: list[dict[str, Any]] | None = None,
    logic_hits: list[dict[str, Any]] | None = None,
    claim_hits: list[dict[str, Any]] | None = None,
    proposition_hits: list[dict[str, Any]] | None = None,
    textbook_hits: list[dict[str, Any]] | None = None,
    k: int = 8,
) -> list[dict[str, Any]]:
    del question
    ordered: dict[str, list[dict[str, Any]]] = {
        "textbook": _sorted_hits(textbook_hits),
        "proposition": _sorted_hits(proposition_hits),
        "claim": _sorted_hits(claim_hits),
        "logic_step": _sorted_hits(logic_hits),
        "chunk": _sorted_hits(chunk_hits),
    }
    plan_order = {
        "textbook_first_then_paper": ["textbook", "proposition", "claim", "logic_step", "chunk"],
        "claim_first": ["claim", "logic_step", "chunk", "proposition", "textbook"],
        "proposition_first": ["proposition", "textbook", "claim", "logic_step", "chunk"],
        "hybrid_parallel": ["claim", "proposition", "logic_step", "textbook", "chunk"],
        "paper_first_then_textbook": ["chunk", "claim", "logic_step", "proposition", "textbook"],
    }
    order = plan_order.get(str(retrieval_plan or "").strip(), plan_order["paper_first_then_textbook"])

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for bucket in order:
        for row in ordered.get(bucket, []):
            key = _hit_key(row)
            if not key[1] or key in seen:
                continue
            seen.add(key)
            out.append(row)
            if len(out) >= max(1, int(k)):
                return out
    return out
