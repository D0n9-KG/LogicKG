from __future__ import annotations

import hashlib
import re
from typing import Any

from app.graph.neo4j_client import Neo4jClient
from app.settings import settings


_WORD_RE = re.compile(r"[a-z0-9]+")
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<!\d)[.!?;。！？；]+(?!\d)")

_FALLBACK_BY_DOMAIN: dict[str, list[dict[str, Any]]] = {
    "granular_flow": [
        {
            "gap_id": "gap:granular_flow:friction_clustering_transition",
            "gap_type": "seed",
            "title": "Friction-driven clustering transition remains under-constrained",
            "description": "Insufficient cross-study comparison on friction impact for clustering transition.",
            "missing_evidence_statement": "Need controlled evidence that isolates contact friction from restitution effects.",
            "priority_score": 0.68,
        },
        {
            "gap_id": "gap:granular_flow:temperature_shear_banding",
            "gap_type": "seed",
            "title": "Granular temperature mechanisms for shear-band onset are fragmented",
            "description": "Mechanistic links between granular temperature and shear-band onset remain fragmented.",
            "missing_evidence_statement": "Need support/challenge evidence across simulation and experimental regimes.",
            "priority_score": 0.66,
        },
    ],
}


def _norm_domain(domain: str) -> str:
    return str(domain or "").strip().lower()


def _domain_keywords(domain: str) -> list[str]:
    normalized = _norm_domain(domain).replace("-", "_")
    if not normalized:
        return []
    return [token for token in _WORD_RE.findall(normalized.replace("_", " ")) if len(token) >= 3]


def _domain_match(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    haystack = str(text or "").lower()
    return any(keyword in haystack for keyword in keywords)


def _gap_id(prefix: str, payload: str) -> str:
    digest = hashlib.sha1(payload.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"gap:{prefix}:{digest}"


def _clamp01(v: float) -> float:
    if v <= 0:
        return 0.0
    if v >= 1:
        return 1.0
    return float(v)


def _clean_text(text: str) -> str:
    return _SPACE_RE.sub(" ", str(text or "")).strip()


def _first_sentence(text: str, *, max_chars: int = 160) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    sentence = _SENTENCE_SPLIT_RE.split(cleaned, maxsplit=1)[0].strip()
    out = sentence or cleaned
    if len(out) > max_chars:
        clipped = out[: max_chars - 1]
        if " " in clipped:
            clipped = clipped.rsplit(" ", 1)[0]
        out = clipped.rstrip(" ,;:-") + "..."
    return out


def _string_list(values: Any) -> list[str]:
    if isinstance(values, (list, tuple, set)):
        return [str(value).strip() for value in values if str(value).strip()]
    text = str(values or "").strip()
    return [text] if text else []


def _community_text(row: dict[str, Any]) -> str:
    title = _clean_text(str(row.get("title") or ""))
    summary = _clean_text(str(row.get("summary") or ""))
    keywords = _string_list(row.get("keywords") or row.get("keyword_texts"))
    return " ".join(part for part in [title, summary, " ".join(keywords)] if part)


def _community_gap_type(row: dict[str, Any]) -> str:
    support_count = int(row.get("paper_support_count") or 0)
    challenge_count = int(row.get("paper_challenge_count") or 0)
    textbook_count = int(row.get("textbook_member_count") or 0)
    paper_count = int(row.get("paper_member_count") or row.get("paper_count") or support_count + challenge_count)
    benchmark_gap_count = int(row.get("benchmark_gap_count") or 0)
    if challenge_count > 0 and support_count > 0:
        return "conflict_hotspot"
    if benchmark_gap_count > 0:
        return "limitation"
    if textbook_count > 0 and paper_count <= 1:
        return "gap_claim"
    if challenge_count > 0:
        return "conflict_hotspot"
    return "seed"


def _community_missing_statement(gap_type: str, row: dict[str, Any]) -> str:
    textbook_count = int(row.get("textbook_member_count") or 0)
    paper_count = int(row.get("paper_member_count") or row.get("paper_count") or 0)
    if gap_type == "conflict_hotspot":
        return "Need member-level support and challenge evidence that explains why this community disagrees across papers."
    if gap_type == "limitation":
        return "Need benchmark and boundary-condition evidence for the weakly covered parts of this community."
    if textbook_count > 0 and paper_count <= 1:
        return "Need more paper-backed evidence for a community that is currently dominated by textbook coverage."
    return "Need additional community-member evidence across papers, settings, and methods."


def _community_title(gap_type: str, row: dict[str, Any]) -> str:
    topic = _first_sentence(str(row.get("title") or row.get("summary") or row.get("community_id") or ""), max_chars=96) or "community"
    if gap_type == "conflict_hotspot":
        return f"Conflicting community evidence needs disambiguation: {topic}"
    if gap_type == "limitation":
        return f"Community limitation remains unresolved: {topic}"
    if gap_type == "gap_claim":
        return f"Community lacks paper-backed evidence: {topic}"
    return f"Open community mechanism gap: {topic}"


def _community_description(row: dict[str, Any]) -> str:
    summary = _clean_text(str(row.get("summary") or ""))
    if summary:
        return summary
    title = _clean_text(str(row.get("title") or ""))
    if title:
        return title
    return "A global community lacks sufficient evidence coverage for high-confidence explanation."


def _from_global_communities(
    client: Neo4jClient,
    keywords: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    rows = client.list_global_community_rows(limit=max(50, limit * 8))
    out: list[dict[str, Any]] = []
    for row in rows:
        community_id = str(row.get("community_id") or "").strip()
        if not community_id:
            continue
        community_text = _community_text(row)
        if not _domain_match(community_text, keywords):
            continue

        member_count = int(row.get("member_count") or 0)
        support_count = int(row.get("paper_support_count") or 0)
        challenge_count = int(row.get("paper_challenge_count") or 0)
        textbook_count = int(row.get("textbook_member_count") or 0)
        paper_count = int(row.get("paper_member_count") or row.get("paper_count") or support_count + challenge_count)
        benchmark_gap_count = int(row.get("benchmark_gap_count") or 0)
        gap_type = _community_gap_type(row)

        disagreement = challenge_count / max(1.0, float(support_count + challenge_count))
        sparse_paper_density = 1.0 - min(1.0, paper_count / max(1.0, float(member_count or 1)))
        textbook_heaviness = min(1.0, textbook_count / max(1.0, float(member_count or 1)))
        benchmark_gap = min(1.0, benchmark_gap_count / 3.0)
        raw_priority = (
            0.28
            + 0.28 * disagreement
            + 0.18 * sparse_paper_density
            + 0.14 * textbook_heaviness
            + 0.12 * benchmark_gap
        )
        if gap_type == "conflict_hotspot":
            raw_priority += 0.06

        out.append(
            {
                "gap_id": _gap_id("community", community_id),
                "gap_type": gap_type,
                "title": _community_title(gap_type, row),
                "description": _community_description(row),
                "missing_evidence_statement": _community_missing_statement(gap_type, row),
                "priority_score": _clamp01(raw_priority),
                "source_community_ids": [community_id],
                "source_paper_ids": _string_list(row.get("paper_ids")),
                "signals": {
                    "member_count": member_count,
                    "paper_support_count": support_count,
                    "paper_challenge_count": challenge_count,
                    "paper_member_count": paper_count,
                    "textbook_member_count": textbook_count,
                    "benchmark_gap_count": benchmark_gap_count,
                    "keywords": _string_list(row.get("keywords") or row.get("keyword_texts")),
                },
            }
        )
    return out


def _dedup_and_sort(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        item = dict(raw or {})
        gap_id = str(item.get("gap_id") or "").strip()
        desc = str(item.get("description") or "").strip()
        if not gap_id:
            gap_id = _gap_id("auto", desc or str(item))
            item["gap_id"] = gap_id
        previous = by_key.get(gap_id)
        if previous is None or float(item.get("priority_score") or 0.0) > float(previous.get("priority_score") or 0.0):
            by_key[gap_id] = item

    ordered = sorted(
        by_key.values(),
        key=lambda item: (
            float(item.get("priority_score") or 0.0),
            str(item.get("gap_type") or ""),
            str(item.get("gap_id") or ""),
        ),
        reverse=True,
    )
    return ordered[: max(1, int(limit))]


def _fallback_gaps(domain: str, limit: int) -> list[dict[str, Any]]:
    normalized = _norm_domain(domain)
    seeds = [dict(item) for item in _FALLBACK_BY_DOMAIN.get(normalized, [])]
    if not seeds:
        seeds = [
            {
                "gap_id": _gap_id("seed", normalized or "global"),
                "gap_type": "seed",
                "title": "Cross-paper unresolved mechanism",
                "description": "Current evidence graph does not yet provide enough support/challenge coverage for a high-confidence mechanism-level hypothesis.",
                "missing_evidence_statement": "Need at least one supporting and one challenging evidence chain across different papers.",
                "priority_score": 0.55,
            }
        ]
    return seeds[: max(1, int(limit))]


def detect_knowledge_gaps(domain: str, limit: int = 8) -> list[dict[str, Any]]:
    final_limit = max(1, min(64, int(limit)))
    keywords = _domain_keywords(domain)
    mined: list[dict[str, Any]] = []

    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            mined.extend(_from_global_communities(client=client, keywords=keywords, limit=final_limit))
    except Exception:
        mined = []

    if not mined:
        return _fallback_gaps(domain=domain, limit=final_limit)

    out = _dedup_and_sort(mined, limit=final_limit)
    if not out:
        return _fallback_gaps(domain=domain, limit=final_limit)
    return out
