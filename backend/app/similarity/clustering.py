"""Proposition grouping with agglomerative / Louvain / hybrid strategies."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from app.similarity.embedding import cosine_similarity


def _group_from_labels(
    *,
    labels: list[int],
    embeddings: list[list[float]],
    texts: list[str],
) -> list[dict[str, Any]]:
    groups: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        groups.setdefault(int(label), []).append(idx)

    result: list[dict[str, Any]] = []
    for label, member_indices in groups.items():
        representative_text = texts[member_indices[0]]
        group_embeddings = [embeddings[i] for i in member_indices]
        centroid = np.mean(group_embeddings, axis=0)
        scores = [cosine_similarity(embeddings[i], centroid.tolist()) for i in member_indices]
        result.append(
            {
                "label": int(label),
                "representative_text": representative_text,
                "member_indices": member_indices,
                "member_count": len(member_indices),
                "avg_similarity": float(np.mean(scores)) if scores else 0.0,
            }
        )
    return result


def _agglomerative_labels(embeddings: list[list[float]], threshold: float) -> list[int]:
    if len(embeddings) <= 1:
        return [0] if embeddings else []
    X = np.array(embeddings)
    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=1 - float(threshold),
        metric="cosine",
        linkage="average",
    )
    raw = clustering.fit_predict(X)
    return [int(x) for x in raw]


def _louvain_labels(embeddings: list[list[float]], threshold: float, max_iter: int = 24) -> list[int]:
    n = len(embeddings)
    if n <= 1:
        return [0] if n == 1 else []

    adjacency: dict[int, dict[int, float]] = {i: {} for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            sim = float(cosine_similarity(embeddings[i], embeddings[j]))
            if sim < float(threshold):
                continue
            w = max(0.0, sim)
            if w <= 0.0:
                continue
            adjacency[i][j] = w
            adjacency[j][i] = w

    degree = {i: float(sum(adjacency[i].values())) for i in range(n)}
    m2 = float(sum(degree.values()))
    if m2 <= 0.0:
        return list(range(n))

    part = {i: i for i in range(n)}
    tot = {i: degree[i] for i in range(n)}

    for _ in range(max(1, int(max_iter))):
        moved = False
        for node in range(n):
            k_i = degree[node]
            if k_i <= 0.0:
                continue
            current = part[node]
            comm_w: dict[int, float] = defaultdict(float)
            for nbr, w in adjacency[node].items():
                comm_w[part[nbr]] += float(w)

            tot[current] = tot.get(current, 0.0) - k_i
            best_comm = current
            best_gain = 0.0
            for comm, k_i_in in comm_w.items():
                gain = float(k_i_in) - (tot.get(comm, 0.0) * k_i / m2)
                if gain > best_gain + 1e-12:
                    best_gain = gain
                    best_comm = comm
            part[node] = best_comm
            tot[best_comm] = tot.get(best_comm, 0.0) + k_i
            if best_comm != current:
                moved = True
        if not moved:
            break

    comm_members: dict[int, list[int]] = defaultdict(list)
    for node, comm in part.items():
        comm_members[int(comm)].append(int(node))
    ordered = sorted(comm_members.items(), key=lambda x: (-len(x[1]), min(x[1])))
    remap = {old: idx for idx, (old, _) in enumerate(ordered)}
    return [remap[int(part[i])] for i in range(n)]


def _hybrid_labels(embeddings: list[list[float]], threshold: float) -> list[int]:
    n = len(embeddings)
    if n <= 1:
        return [0] if n == 1 else []

    coarse_threshold = max(0.0, min(1.0, float(threshold) - 0.03))
    coarse = _louvain_labels(embeddings, threshold=coarse_threshold)
    buckets: dict[int, list[int]] = {}
    for idx, c in enumerate(coarse):
        buckets.setdefault(int(c), []).append(idx)

    labels = [-1] * n
    label_cursor = 0
    for _, members in sorted(buckets.items(), key=lambda x: (len(x[1]), x[0]), reverse=True):
        if len(members) <= 2:
            for idx in members:
                labels[idx] = label_cursor
            label_cursor += 1
            continue
        sub_embeddings = [embeddings[i] for i in members]
        sub_labels = _agglomerative_labels(sub_embeddings, threshold=float(threshold))
        sub_to_global: dict[int, int] = {}
        for pos, sub_label in enumerate(sub_labels):
            if sub_label not in sub_to_global:
                sub_to_global[sub_label] = label_cursor
                label_cursor += 1
            labels[members[pos]] = sub_to_global[sub_label]

    # Fallback guard: ensure no label is missing
    for i in range(n):
        if labels[i] < 0:
            labels[i] = label_cursor
            label_cursor += 1
    return labels


def cluster_propositions(
    embeddings: list[list[float]],
    texts: list[str],
    threshold: float = 0.85,
    min_shared_anchors: int = 1,
    method: str = "agglomerative",
) -> list[dict[str, Any]]:
    """
    Cluster propositions using Agglomerative Clustering with constraints.

    Args:
        embeddings: List of embedding vectors
        texts: List of proposition texts (parallel to embeddings)
        threshold: Similarity threshold for merging (0.82-0.88 recommended)
        min_shared_anchors: Minimum shared anchor words required (currently unused)

    Returns:
        List of groups, each containing member indices and representative text
    """
    _ = min_shared_anchors  # reserved for future lexical-anchor constraints
    if not embeddings or len(embeddings) != len(texts):
        return []

    if len(embeddings) == 1:
        return [
            {
                "label": 0,
                "representative_text": texts[0],
                "member_indices": [0],
                "member_count": 1,
                "avg_similarity": 1.0,
            }
        ]

    normalized = str(method or "agglomerative").strip().lower()
    if normalized not in {"agglomerative", "louvain", "hybrid"}:
        normalized = "agglomerative"

    if normalized == "louvain":
        labels = _louvain_labels(embeddings, threshold=threshold)
    elif normalized == "hybrid":
        labels = _hybrid_labels(embeddings, threshold=threshold)
    else:
        labels = _agglomerative_labels(embeddings, threshold=threshold)

    return _group_from_labels(labels=labels, embeddings=embeddings, texts=texts)
