from __future__ import annotations

import hashlib
import re
from typing import Any

from app.graph.neo4j_client import Neo4jClient
from app.settings import settings


_WORD_RE = re.compile(r"[a-z0-9]+")
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<!\d)[.!?;。！？；]+(?!\d)")
_GENERIC_SIGNAL_RE = re.compile(
    r"^(gap|future\s*work|limitation|critique)\s+signal\s+from\s+(claim|extracted\s+gap\s+seed)\b[:：]?\s*",
    flags=re.IGNORECASE,
)
_LEADING_FILLER_RE = re.compile(
    r"^(this\s+(paper|study|work)\s+(suggests|shows|indicates|highlights)\s+that\s+|"
    r"it\s+is\s+important\s+to\s+note\s+that\s+|"
    r"the\s+main\s+limitation\s+is\s+that\s+)",
    flags=re.IGNORECASE,
)

_DEFAULT_GAP_CLAIM_KINDS = ["Gap", "FutureWork", "Limitation", "Critique"]

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
    return [x for x in _WORD_RE.findall(normalized.replace("_", " ")) if len(x) >= 3]


def _domain_match(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    t = str(text or "").lower()
    return any(k in t for k in keywords)


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
    merged = _SPACE_RE.sub(" ", str(text or "")).strip()
    if not merged:
        return ""
    merged = _GENERIC_SIGNAL_RE.sub("", merged).strip()
    merged = _LEADING_FILLER_RE.sub("", merged).strip()
    return merged


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
        out = clipped.rstrip(" ,;:-") + "…"
    return out


def _topic_hint(row: dict[str, Any]) -> str:
    for key in ("text", "prop_text"):
        candidate = _first_sentence(str(row.get(key) or ""), max_chars=120)
        if candidate:
            return candidate
    title = _first_sentence(str(row.get("paper_title") or ""), max_chars=96)
    if title:
        return title
    return "the reported open issue"


def _human_title_for_gap(gap_type: str, row: dict[str, Any]) -> str:
    topic = _topic_hint(row)
    if gap_type == "future_work":
        return f"Future direction needs validation: {topic}"
    if gap_type == "limitation":
        return f"Method limitation remains unresolved: {topic}"
    if gap_type == "conflict_hotspot":
        return f"Conflicting evidence requires disambiguation: {topic}"
    if gap_type == "challenged_proposition":
        return f"Challenged proposition needs boundary testing: {topic}"
    return f"Open mechanism gap: {topic}"


def _human_description_for_gap(gap_type: str, row: dict[str, Any]) -> str:
    text = _clean_text(str(row.get("text") or ""))
    prop_text = _clean_text(str(row.get("prop_text") or ""))
    paper_title = _clean_text(str(row.get("paper_title") or ""))
    if len(text) >= 24:
        desc = text
    elif len(prop_text) >= 24:
        desc = prop_text
    elif paper_title:
        desc = f"The issue appears in: {paper_title}."
    else:
        desc = "Insufficiently specified claim text requires deeper extraction and validation."
    return desc


def _pick_gap_type(kinds: list[str]) -> str:
    lowered = {str(k).strip().lower() for k in kinds}
    if "futurework" in lowered:
        return "future_work"
    if "limitation" in lowered:
        return "limitation"
    if "critique" in lowered:
        return "limitation"
    if "gap" in lowered:
        return "gap_claim"
    return "gap_claim"


def _missing_statement_for_kind(kind: str) -> str:
    if kind == "future_work":
        return "Need concrete validation protocol and measurable success criteria for the future direction."
    if kind == "limitation":
        return "Need evidence that quantifies boundary conditions and failure modes of current methods."
    return "Need support/challenge evidence across datasets, settings, and methodological variants."


def _from_conflict_hotspots(
    client: Neo4jClient,
    keywords: list[str],
    limit: int,
) -> list[dict]:
    rows = client.list_conflict_hotspots(limit=max(50, limit * 4), min_events=1)
    out: list[dict] = []
    for r in rows:
        prop_id = str(r.get("prop_id") or "").strip()
        text = str(r.get("canonical_text") or "").strip()
        if not prop_id or not text:
            continue
        if not _domain_match(text, keywords):
            continue

        conflict_events = int(r.get("conflict_events") or 0)
        supersede_events = int(r.get("supersede_events") or 0)
        challenge_events = int(r.get("challenge_events") or 0)
        paper_count = int(r.get("source_paper_count") or 0)
        raw_priority = 0.35 + 0.08 * min(conflict_events, 5) + 0.04 * min(supersede_events + challenge_events, 5)
        raw_priority += 0.03 * min(paper_count, 5)

        out.append(
            {
                "gap_id": f"gap:conflict:{prop_id}",
                "gap_type": "conflict_hotspot",
                "title": f"Conflicting evidence around proposition: {text[:84]}",
                "description": f"Conflict hotspot detected ({conflict_events} challenge/supersede events) for proposition \"{text}\".",
                "missing_evidence_statement": "Need disambiguating evidence and condition-specific comparisons to resolve conflicting findings.",
                "priority_score": _clamp01(raw_priority),
                "source_proposition_ids": [prop_id],
                "signals": {
                    "conflict_events": conflict_events,
                    "challenge_events": challenge_events,
                    "supersede_events": supersede_events,
                    "source_paper_count": paper_count,
                },
            }
        )
    return out


def _from_gap_like_claims(
    client: Neo4jClient,
    keywords: list[str],
    limit: int,
) -> list[dict]:
    rows = client.list_gap_like_claims(limit=max(80, limit * 8), kinds=_DEFAULT_GAP_CLAIM_KINDS)
    out: list[dict] = []
    for r in rows:
        claim_id = str(r.get("claim_id") or "").strip()
        text = str(r.get("text") or "").strip()
        if not claim_id or not text:
            continue
        if not _domain_match(text, keywords):
            continue
        kinds = [str(k).strip() for k in (r.get("kinds") or []) if str(k).strip()]
        gap_type = _pick_gap_type(kinds)
        confidence = float(r.get("confidence") or 0.0)
        evidence_count = int(r.get("evidence_count") or 0)
        prop_id = str(r.get("prop_id") or "").strip()
        paper_id = str(r.get("paper_id") or "").strip()
        paper_title = str(r.get("paper_title") or "").strip()

        raw_priority = 0.38 + 0.35 * _clamp01(confidence) + 0.07 * min(evidence_count, 4)
        if gap_type == "future_work":
            raw_priority += 0.06
        if gap_type == "limitation":
            raw_priority += 0.05

        out.append(
            {
                "gap_id": _gap_id("claim", claim_id),
                "gap_type": gap_type,
                "title": _human_title_for_gap(gap_type, r),
                "description": _human_description_for_gap(gap_type, r),
                "missing_evidence_statement": _missing_statement_for_kind(gap_type),
                "priority_score": _clamp01(raw_priority),
                "source_claim_ids": [claim_id],
                "source_proposition_ids": [prop_id] if prop_id else [],
                "source_paper_ids": [paper_id] if paper_id else [],
                "signals": {
                    "confidence": confidence,
                    "evidence_count": evidence_count,
                    "paper_title": paper_title,
                    "kinds": kinds,
                },
            }
        )
    return out


def _from_gap_seeds(
    client: Neo4jClient,
    keywords: list[str],
    limit: int,
) -> list[dict]:
    rows = client.list_gap_seeds(limit=max(80, limit * 8), kinds=_DEFAULT_GAP_CLAIM_KINDS)
    out: list[dict] = []
    for r in rows:
        seed_id = str(r.get("seed_id") or "").strip()
        text = str(r.get("text") or "").strip()
        if not seed_id or not text:
            continue
        if not _domain_match(text, keywords):
            continue
        kinds = [str(k).strip() for k in (r.get("kinds") or []) if str(k).strip()]
        gap_type = _pick_gap_type(kinds)
        confidence = float(r.get("confidence") or 0.0)
        prop_id = str(r.get("prop_id") or "").strip()
        paper_id = str(r.get("paper_id") or "").strip()
        paper_title = str(r.get("paper_title") or "").strip()

        raw_priority = 0.4 + 0.4 * _clamp01(confidence)
        if gap_type in {"future_work", "limitation"}:
            raw_priority += 0.06

        out.append(
            {
                "gap_id": _gap_id("seed", seed_id),
                "gap_type": gap_type,
                "title": _human_title_for_gap(gap_type, r),
                "description": _human_description_for_gap(gap_type, r),
                "missing_evidence_statement": _missing_statement_for_kind(gap_type),
                "priority_score": _clamp01(raw_priority),
                "source_claim_ids": [str(r.get("claim_id") or "").strip()] if str(r.get("claim_id") or "").strip() else [],
                "source_proposition_ids": [prop_id] if prop_id else [],
                "source_paper_ids": [paper_id] if paper_id else [],
                "signals": {
                    "confidence": confidence,
                    "paper_title": paper_title,
                    "kinds": kinds,
                    "origin": "knowledge_gap_seed",
                },
            }
        )
    return out


def _from_challenged_propositions(
    client: Neo4jClient,
    keywords: list[str],
    limit: int,
) -> list[dict]:
    rows = client.list_propositions(limit=max(60, limit * 6), state="challenged")
    out: list[dict] = []
    for r in rows:
        prop_id = str(r.get("prop_id") or "").strip()
        text = str(r.get("canonical_text") or "").strip()
        if not prop_id or not text:
            continue
        if not _domain_match(text, keywords):
            continue

        challenges = int(r.get("challenges") or 0)
        supports = int(r.get("supports") or 0)
        supersedes = int(r.get("supersedes") or 0)
        mention_count = int(r.get("mention_count") or 0)
        score = float(r.get("current_score") or 0.0)
        raw_priority = 0.3 + 0.06 * min(challenges + supersedes, 6) + 0.04 * min(mention_count, 6)
        raw_priority += 0.15 * (1.0 - _clamp01(score))

        out.append(
            {
                "gap_id": f"gap:challenged:{prop_id}",
                "gap_type": "challenged_proposition",
                "title": f"Challenged proposition requires targeted hypothesis testing",
                "description": text,
                "missing_evidence_statement": "Need targeted experiments or analyses that explain when this proposition holds or fails.",
                "priority_score": _clamp01(raw_priority),
                "source_proposition_ids": [prop_id],
                "signals": {
                    "supports": supports,
                    "challenges": challenges,
                    "supersedes": supersedes,
                    "mention_count": mention_count,
                    "current_score": score,
                },
            }
        )
    return out


def _dedup_and_sort(candidates: list[dict], limit: int) -> list[dict]:
    by_key: dict[str, dict] = {}
    for raw in candidates:
        item = dict(raw or {})
        gid = str(item.get("gap_id") or "").strip()
        desc = str(item.get("description") or "").strip()
        if not gid:
            gid = _gap_id("auto", desc or str(item))
            item["gap_id"] = gid
        prev = by_key.get(gid)
        if prev is None:
            by_key[gid] = item
            continue
        if float(item.get("priority_score") or 0.0) > float(prev.get("priority_score") or 0.0):
            by_key[gid] = item

    ordered = sorted(
        by_key.values(),
        key=lambda x: (
            float(x.get("priority_score") or 0.0),
            str(x.get("gap_type") or ""),
            str(x.get("gap_id") or ""),
        ),
        reverse=True,
    )
    return ordered[: max(1, int(limit))]


def _fallback_gaps(domain: str, limit: int) -> list[dict]:
    normalized = _norm_domain(domain)
    seeds = [dict(x) for x in _FALLBACK_BY_DOMAIN.get(normalized, [])]
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


def detect_knowledge_gaps(domain: str, limit: int = 8) -> list[dict]:
    """Detect research gaps from graph signals, with deterministic fallback."""
    final_limit = max(1, min(64, int(limit)))
    keywords = _domain_keywords(domain)
    mined: list[dict] = []

    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            mined.extend(_from_conflict_hotspots(client=client, keywords=keywords, limit=final_limit))
            mined.extend(_from_gap_seeds(client=client, keywords=keywords, limit=final_limit))
            mined.extend(_from_gap_like_claims(client=client, keywords=keywords, limit=final_limit))
            mined.extend(_from_challenged_propositions(client=client, keywords=keywords, limit=final_limit))
    except Exception:
        mined = []

    if not mined:
        return _fallback_gaps(domain=domain, limit=final_limit)

    out = _dedup_and_sort(mined, limit=final_limit)
    if not out:
        return _fallback_gaps(domain=domain, limit=final_limit)
    return out
