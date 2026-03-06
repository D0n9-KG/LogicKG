from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any


_TOKEN_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+")
_SPACE_RE = re.compile(r"\s+")


def _tokenize(text: str) -> set[str]:
    return {tok.lower() for tok in _TOKEN_RE.findall(str(text or ""))}


def _normalize_text(text: str) -> str:
    return _SPACE_RE.sub(" ", str(text or "").strip())


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter <= 0:
        return 0.0
    return inter / max(1, len(a | b))


def detect_fusion_communities(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    min_edge_weight: float = 0.5,
    semantic_threshold: float = 0.55,
) -> list[dict[str, Any]]:
    node_map = {str(n.get("id") or "").strip(): n for n in nodes if str(n.get("id") or "").strip()}
    if not node_map:
        return []

    adjacency: dict[str, set[str]] = {nid: set() for nid in node_map}
    weighted_pairs: list[tuple[str, str, float]] = []

    for edge in edges:
        s = str(edge.get("source") or "").strip()
        t = str(edge.get("target") or "").strip()
        if not s or not t or s not in node_map or t not in node_map:
            continue
        w = float(edge.get("weight") or 0.0)
        if w >= float(min_edge_weight):
            adjacency[s].add(t)
            adjacency[t].add(s)
            weighted_pairs.append((s, t, w))

    # TreeComm-style light semantic refinement: connect semantically-close isolated nodes.
    node_tokens = {
        nid: _tokenize(f"{node_map[nid].get('text', '')} {node_map[nid].get('evidence_quote', '')}")
        for nid in node_map
    }
    ids = sorted(node_map.keys())
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a = ids[i]
            b = ids[j]
            if b in adjacency[a]:
                continue
            sim = _jaccard(node_tokens[a], node_tokens[b])
            if sim >= float(semantic_threshold):
                adjacency[a].add(b)
                adjacency[b].add(a)
                weighted_pairs.append((a, b, sim))

    visited: set[str] = set()
    communities: list[dict[str, Any]] = []

    for start in ids:
        if start in visited:
            continue
        stack = [start]
        members: list[str] = []
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            members.append(cur)
            for nxt in sorted(adjacency.get(cur, ())):
                if nxt not in visited:
                    stack.append(nxt)

        members_sorted = sorted(members)
        internal_weights = [
            w for a, b, w in weighted_pairs if a in set(members_sorted) and b in set(members_sorted)
        ]
        confidence = (
            sum(internal_weights) / max(1, len(internal_weights))
            if internal_weights
            else 0.5
        )

        representative = max(
            members_sorted,
            key=lambda nid: (len(adjacency.get(nid, set())), len(str(node_map[nid].get("text") or "")), nid),
        )
        rep_node = node_map[representative]
        rep_evidence = _normalize_text(
            str(rep_node.get("evidence_quote") or rep_node.get("text") or "")
        )
        if not rep_evidence:
            rep_evidence = representative

        title_tokens = sorted(
            _tokenize(" ".join(str(node_map[nid].get("text") or "") for nid in members_sorted))
        )
        title = " / ".join(title_tokens[:3]) if title_tokens else f"community {len(communities) + 1}"

        seed = "|".join(members_sorted)
        cid = "fc:" + hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:12]
        communities.append(
            {
                "community_id": cid,
                "title": title,
                "member_ids": members_sorted,
                "confidence": round(float(confidence), 6),
                "representative_evidence": rep_evidence,
                "weight": round(float(confidence), 6),
            }
        )

    communities.sort(key=lambda c: c["community_id"])
    return communities
