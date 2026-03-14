from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.community.overview_graph import build_overview_community_graph
from app.graph.neo4j_client import Neo4jClient
from app.settings import settings


router = APIRouter(prefix="/community", tags=["community"])


@router.get("/list")
def list_global_communities(limit: int = 200):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return {"communities": client.list_global_community_rows(limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/overview-graph")
def get_overview_graph(
    community_limit: int = 18,
    member_limit_per_community: int = 6,
    max_nodes: int = 160,
    max_edges: int = 240,
):
    try:
        safe_community_limit = max(1, min(80, int(community_limit)))
        safe_member_limit = max(1, min(24, int(member_limit_per_community)))
        safe_max_nodes = max(8, min(800, int(max_nodes)))
        safe_max_edges = max(8, min(1600, int(max_edges)))

        fetch_community_limit = min(5000, max(safe_community_limit * 6, safe_community_limit))
        fetch_member_limit = min(120, max(safe_member_limit * 4, safe_member_limit + 4))

        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            community_rows = client.list_global_community_rows(limit=fetch_community_limit)
            members_by_community = {
                str(row.get("community_id") or "").strip(): client.list_global_community_members(
                    str(row.get("community_id") or "").strip(),
                    limit=fetch_member_limit,
                )
                for row in community_rows
                if str(row.get("community_id") or "").strip()
            }
        return build_overview_community_graph(
            community_rows,
            members_by_community,
            community_limit=safe_community_limit,
            member_limit_per_community=safe_member_limit,
            max_nodes=safe_max_nodes,
            max_edges=safe_max_edges,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{community_id}")
def get_global_community(community_id: str, member_limit: int = 200):
    community_key = str(community_id or "").strip()
    if not community_key:
        raise HTTPException(status_code=400, detail="community_id is required")

    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            communities = client.list_global_community_rows(limit=50000)
            detail = next((row for row in communities if str(row.get("community_id") or "").strip() == community_key), None)
            if detail is None:
                raise HTTPException(status_code=404, detail=f"Community not found: {community_key}")
            members = client.list_global_community_members(community_key, limit=member_limit)
            return {**detail, "members": members}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
