from __future__ import annotations

from collections import defaultdict


def _local_louvain_partition(nodes: list[str], edges: list[tuple[str, str, float]], max_iter: int = 24) -> dict[str, int]:
    node_ids = [str(n).strip() for n in (nodes or []) if str(n).strip()]
    if not node_ids:
        return {}
    if len(node_ids) == 1:
        return {node_ids[0]: 0}

    adjacency: dict[str, dict[str, float]] = {nid: {} for nid in node_ids}
    for raw_u, raw_v, raw_w in edges or []:
        u = str(raw_u or "").strip()
        v = str(raw_v or "").strip()
        if not u or not v or u == v:
            continue
        if u not in adjacency or v not in adjacency:
            continue
        w = float(raw_w or 0.0)
        if w <= 0.0:
            continue
        adjacency[u][v] = adjacency[u].get(v, 0.0) + w
        adjacency[v][u] = adjacency[v].get(u, 0.0) + w

    degree = {nid: float(sum(adjacency[nid].values())) for nid in node_ids}
    m2 = float(sum(degree.values()))
    if m2 <= 0.0:
        return {nid: idx for idx, nid in enumerate(sorted(node_ids))}

    part = {nid: idx for idx, nid in enumerate(sorted(node_ids))}
    tot = {part[nid]: degree[nid] for nid in node_ids}

    for _ in range(max(1, int(max_iter))):
        moved = False
        for nid in sorted(node_ids):
            k_i = degree.get(nid, 0.0)
            if k_i <= 0.0:
                continue
            current = part[nid]
            comm_w: dict[int, float] = defaultdict(float)
            for nbr, w in adjacency[nid].items():
                comm_w[part[nbr]] += float(w)

            tot[current] = tot.get(current, 0.0) - k_i
            best_comm = current
            best_gain = 0.0
            for comm, k_i_in in comm_w.items():
                gain = float(k_i_in) - (tot.get(comm, 0.0) * k_i / m2)
                if gain > best_gain + 1e-12:
                    best_gain = gain
                    best_comm = comm

            part[nid] = best_comm
            tot[best_comm] = tot.get(best_comm, 0.0) + k_i
            if best_comm != current:
                moved = True
        if not moved:
            break

    comm_to_nodes: dict[int, list[str]] = defaultdict(list)
    for nid, comm in part.items():
        comm_to_nodes[int(comm)].append(nid)
    ordered_comms = sorted(comm_to_nodes.items(), key=lambda item: (-len(item[1]), min(item[1])))
    remap = {old: idx for idx, (old, _) in enumerate(ordered_comms)}
    return {nid: remap[int(comm)] for nid, comm in part.items()}

def _community_label(member_ids: list[str], entity_by_id: dict[str, dict]) -> str:
    names = []
    for member_id in member_ids:
        name = str(entity_by_id.get(member_id, {}).get("name") or "").strip()
        if name:
            names.append(name)
        if len(names) >= 3:
            break
    if not names:
        return f"Cluster {len(member_ids)}"
    return " / ".join(names)


def build_community_rows(entities: list[dict], relations: list[dict]) -> list[dict]:
    entity_rows = [dict(item) for item in (entities or []) if str(item.get("entity_id") or "").strip()]
    relation_rows = [dict(item) for item in (relations or [])]
    if not entity_rows:
        return []

    entity_by_id = {str(item["entity_id"]): item for item in entity_rows}
    rows: list[dict] = []
    unassigned_ids = sorted(entity_by_id.keys())
    if unassigned_ids:
        unassigned_set = set(unassigned_ids)
        weighted_edges = []
        for rel in relation_rows:
            src = str(rel.get("source_id") or "").strip()
            tgt = str(rel.get("target_id") or "").strip()
            if not src or not tgt or src == tgt:
                continue
            if src in unassigned_set and tgt in unassigned_set:
                weighted_edges.append((src, tgt, 1.0))

        partition = _local_louvain_partition(unassigned_ids, weighted_edges)
        groups: dict[int, list[str]] = defaultdict(list)
        if partition:
            for entity_id in unassigned_ids:
                groups[int(partition.get(entity_id, -1))].append(entity_id)
        else:
            for idx, entity_id in enumerate(unassigned_ids):
                groups[idx].append(entity_id)

        ordered_groups = sorted(groups.values(), key=lambda member_ids: (-len(member_ids), member_ids[0]))
        for idx, member_ids in enumerate(ordered_groups, start=1):
            members = sorted(set(member_ids))
            rows.append(
                {
                    "community_id": f"community:derived:{idx}",
                    "label": _community_label(members, entity_by_id),
                    "member_ids": members,
                    "size": len(members),
                    "source": "derived",
                }
            )

    rows.sort(key=lambda row: (-int(row.get("size") or 0), str(row.get("community_id") or "")))
    return rows


def sample_connected_graph_rows(
    entities: list[dict],
    relations: list[dict],
    *,
    entity_limit: int,
    edge_limit: int,
) -> tuple[list[dict], list[dict]]:
    entity_limit = max(1, int(entity_limit or 0))
    edge_limit = max(0, int(edge_limit or 0))
    entity_by_id = {str(item.get("entity_id") or "").strip(): dict(item) for item in (entities or []) if str(item.get("entity_id") or "").strip()}
    if not entity_by_id:
        return [], []

    valid_relations = []
    for rel in relations or []:
        src = str(rel.get("source_id") or "").strip()
        tgt = str(rel.get("target_id") or "").strip()
        if not src or not tgt or src == tgt:
            continue
        if src not in entity_by_id or tgt not in entity_by_id:
            continue
        valid_relations.append(dict(rel))

    degree: dict[str, int] = defaultdict(int)
    for rel in valid_relations:
        degree[str(rel["source_id"])] += 1
        degree[str(rel["target_id"])] += 1

    def _entity_sort_key(entity_id: str) -> tuple[int, str]:
        entity = entity_by_id.get(entity_id, {})
        return (-(degree.get(entity_id, 0)), str(entity.get("name") or entity_id))

    sorted_relations = sorted(
        valid_relations,
        key=lambda rel: (
            -(degree.get(str(rel.get("source_id") or ""), 0) + degree.get(str(rel.get("target_id") or ""), 0)),
            str(rel.get("rel_type") or ""),
            str(rel.get("source_id") or ""),
            str(rel.get("target_id") or ""),
        ),
    )

    selected_relation_keys: set[tuple[str, str, str]] = set()
    selected_relations: list[dict] = []
    selected_ids: set[str] = set()

    for rel in sorted_relations:
        if len(selected_relations) >= edge_limit:
            break
        src = str(rel.get("source_id") or "")
        tgt = str(rel.get("target_id") or "")
        key = (src, tgt, str(rel.get("rel_type") or ""))
        if key in selected_relation_keys:
            continue
        prospective = selected_ids | {src, tgt}
        if len(prospective) > entity_limit:
            continue
        selected_relation_keys.add(key)
        selected_relations.append(rel)
        selected_ids = prospective

    chapter_buckets: dict[str, list[str]] = defaultdict(list)
    for entity_id, entity in entity_by_id.items():
        chapter_buckets[str(entity.get("source_chapter_id") or "")].append(entity_id)
    for bucket in chapter_buckets.values():
        bucket.sort(key=_entity_sort_key)

    while len(selected_ids) < entity_limit and chapter_buckets:
        progressed = False
        for chapter_id in sorted(chapter_buckets.keys()):
            bucket = chapter_buckets.get(chapter_id) or []
            while bucket and bucket[0] in selected_ids:
                bucket.pop(0)
            if not bucket:
                chapter_buckets.pop(chapter_id, None)
                continue
            selected_ids.add(bucket.pop(0))
            progressed = True
            if len(selected_ids) >= entity_limit:
                break
        if not progressed:
            break

    if len(selected_ids) < entity_limit:
        for entity_id in sorted(entity_by_id.keys(), key=_entity_sort_key):
            selected_ids.add(entity_id)
            if len(selected_ids) >= entity_limit:
                break

    if len(selected_relations) < edge_limit:
        for rel in sorted_relations:
            if len(selected_relations) >= edge_limit:
                break
            src = str(rel.get("source_id") or "")
            tgt = str(rel.get("target_id") or "")
            key = (src, tgt, str(rel.get("rel_type") or ""))
            if key in selected_relation_keys:
                continue
            if src in selected_ids and tgt in selected_ids:
                selected_relation_keys.add(key)
                selected_relations.append(rel)

    selected_entities = sorted((entity_by_id[entity_id] for entity_id in selected_ids), key=lambda item: _entity_sort_key(str(item.get("entity_id") or "")))
    return selected_entities[:entity_limit], selected_relations[:edge_limit]
