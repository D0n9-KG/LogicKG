from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.graph.neo4j_client import Neo4jClient
from app.settings import settings
from app.tasks.clustering_task import run_proposition_clustering


router = APIRouter(prefix="/evolution", tags=["evolution"])


@router.get("/propositions")
def list_propositions(limit: int = 100, state: str | None = None, q: str | None = None):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return {"propositions": client.list_propositions(limit=limit, state=state, query=q)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/proposition/{prop_id}")
def get_proposition(prop_id: str, limit_events: int = 200):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return client.get_proposition_detail(prop_id=prop_id, limit_events=limit_events)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/hotspots")
def list_hotspots(limit: int = 50, min_events: int = 1):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return {"hotspots": client.list_conflict_hotspots(limit=limit, min_events=min_events)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/groups")
def list_groups(limit: int = 100, q: str | None = None):
    try:
        limit = max(1, min(500, int(limit)))
        search_term = (q or "").strip().lower()
        cypher = """
MATCH (pg:PropositionGroup)
WHERE $q = '' OR toLower(coalesce(pg.label_text, '')) CONTAINS $q
OPTIONAL MATCH (p:Proposition)-[:IN_GROUP]->(pg)
WITH pg, count(p) AS actual_prop_count
RETURN pg.group_id AS group_id,
       pg.label_text AS label_text,
       coalesce(pg.proposition_count, 0) AS proposition_count,
       actual_prop_count,
       coalesce(pg.paper_count, 0) AS paper_count,
       pg.embedding_model AS embedding_model,
       pg.model_version AS model_version,
       pg.similarity_threshold AS similarity_threshold,
       pg.clustering_method AS clustering_method,
       pg.build_status AS build_status,
       pg.updated_at AS updated_at,
       pg.created_at AS created_at
ORDER BY actual_prop_count DESC, pg.updated_at DESC, pg.group_id
LIMIT $limit
"""
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            with client._driver.session() as session:
                rows = session.run(cypher, q=search_term, limit=limit)
                groups = [dict(record) for record in rows]
        return {"groups": groups}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/group/{group_id}")
def get_group(group_id: str, limit_propositions: int = 50):
    gid = (group_id or "").strip()
    if not gid:
        raise HTTPException(status_code=400, detail="group_id is required")

    try:
        limit_propositions = max(1, min(500, int(limit_propositions)))
        summary_cypher = """
MATCH (pg:PropositionGroup {group_id: $group_id})
OPTIONAL MATCH (p:Proposition)-[:IN_GROUP]->(pg)
RETURN pg.group_id AS group_id,
       pg.label_text AS label_text,
       coalesce(pg.proposition_count, 0) AS proposition_count,
       count(p) AS actual_prop_count,
       coalesce(pg.paper_count, 0) AS paper_count,
       pg.embedding_model AS embedding_model,
       pg.model_version AS model_version,
       pg.similarity_threshold AS similarity_threshold,
       pg.clustering_method AS clustering_method,
       pg.build_status AS build_status,
       pg.updated_at AS updated_at,
       pg.created_at AS created_at
"""
        members_cypher = """
MATCH (p:Proposition)-[r:IN_GROUP]->(:PropositionGroup {group_id: $group_id})
RETURN p.prop_id AS prop_id,
       p.canonical_text AS canonical_text,
       coalesce(p.paper_count, 0) AS paper_count,
       coalesce(p.current_state, '') AS current_state,
       coalesce(p.current_score, 0.0) AS current_score,
       coalesce(r.similarity_score, 0.0) AS similarity_score,
       coalesce(p.step_types_seen, []) AS step_types_seen,
       coalesce(p.kinds_seen, []) AS kinds_seen
ORDER BY similarity_score DESC, p.prop_id
LIMIT $limit
"""
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            with client._driver.session() as session:
                summary_row = session.run(summary_cypher, group_id=gid).single()
                if not summary_row:
                    raise KeyError(f"group not found: {gid}")
                group = dict(summary_row)
                members = [
                    dict(record)
                    for record in session.run(members_cypher, group_id=gid, limit=limit_propositions)
                ]

        group["propositions"] = members
        return group
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/rebuild-groups")
def rebuild_groups():
    try:
        return run_proposition_clustering(task_id="manual_rebuild")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
