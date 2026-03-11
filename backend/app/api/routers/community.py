from __future__ import annotations

from fastapi import APIRouter, HTTPException

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
