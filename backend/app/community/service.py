from __future__ import annotations

from typing import Any, Callable

from app.community.projection import build_global_projection
from app.community.tree_comm_adapter import run_tree_comm
from app.graph.neo4j_client import Neo4jClient
from app.settings import settings


ProgressFn = Callable[[str, float, str | None], None]
LogFn = Callable[[str], None]


def _noop_progress(stage: str, p: float, msg: str | None = None) -> None:
    del stage, p, msg


def _noop_log(line: str) -> None:
    del line


def rebuild_global_communities(
    *,
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    progress = progress or _noop_progress
    log = log or _noop_log

    progress("community:init", 0.05, "Preparing global community rebuild")
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        client.ensure_schema()

        progress("community:projection", 0.25, "Building whole-graph community projection")
        graph = build_global_projection(client=client)
        projection_nodes = int(getattr(graph, "number_of_nodes", lambda: 0)())
        projection_edges = int(getattr(graph, "number_of_edges", lambda: 0)())
        log(f"global community projection: nodes={projection_nodes}, edges={projection_edges}")

        progress("community:cluster", 0.6, "Running local TreeComm clustering")
        result = run_tree_comm(
            graph,
            top_keywords=settings.global_community_top_keywords,
            version=settings.global_community_version,
        )
        communities = list(result.get("communities") or [])
        keywords = list(result.get("keywords") or [])

        progress("community:write", 0.85, "Writing global communities to Neo4j")
        cleared = client.clear_global_communities()
        communities_written = client.upsert_global_communities(communities)
        keywords_written = client.upsert_global_keywords(keywords)
        membership_rows = []
        for row in communities:
            community_id = str(row.get("community_id") or "").strip()
            for member_id in row.get("member_ids") or []:
                membership_rows.append(
                    {
                        "community_id": community_id,
                        "member_id": str(member_id or "").strip(),
                        "weight": float(row.get("confidence") or 0.0),
                    }
                )
        memberships_written = client.replace_global_memberships(membership_rows)

    progress("community:done", 1.0, "Global community rebuild complete")
    return {
        "ok": True,
        "projection_nodes": projection_nodes,
        "projection_edges": projection_edges,
        "communities": len(communities),
        "keywords": len(keywords),
        "communities_written": int(communities_written),
        "keywords_written": int(keywords_written),
        "memberships_written": int(memberships_written),
        "cleared": cleared,
        "version": settings.global_community_version,
    }
