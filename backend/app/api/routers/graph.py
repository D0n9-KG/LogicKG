from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.crossref.client import CrossrefClient
from app.graph.neo4j_client import Neo4jClient
from app.settings import settings


router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/papers")
def list_papers(limit: int = 50, collection_id: str | None = None):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return {"papers": client.list_papers(limit=limit, collection_id=collection_id)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/paper/{paper_id:path}")
def get_paper(paper_id: str):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return client.get_paper_detail(paper_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/unresolved")
def list_unresolved(limit: int = 100):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return {"unresolved": client.list_unresolved(limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/network")
def network(
    limit_papers: int = 200,
    limit_edges: int = 500,
    collection_id: str | None = None,
    paper_ids: str | None = None,
):
    try:
        ids: list[str] | None = None
        if paper_ids:
            ids = [s.strip() for s in str(paper_ids).split(",") if s.strip()]
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return client.get_network(
                limit_papers=limit_papers,
                limit_edges=limit_edges,
                collection_id=collection_id,
                paper_ids=ids,
            )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/search")
def search_papers(q: str, limit: int = 20, collection_id: str | None = None):
    try:
        query = (q or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="q is required")
        limit = max(1, min(200, int(limit)))
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return {"papers": client.search_papers(query=query, limit=limit, collection_id=collection_id)}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/neighborhood")
def neighborhood(
    paper_id: str,
    depth: int = 1,
    limit_nodes: int = 200,
    limit_edges: int = 400,
    collection_id: str | None = None,
):
    try:
        pid = (paper_id or "").strip()
        if not pid:
            raise HTTPException(status_code=400, detail="paper_id is required")
        depth = max(1, min(1, int(depth)))  # v1: depth=1 only (predictable graph size)
        limit_nodes = max(1, min(2000, int(limit_nodes)))
        limit_edges = max(1, min(4000, int(limit_edges)))
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return client.get_neighborhood(
                paper_id=pid,
                depth=depth,
                limit_nodes=limit_nodes,
                limit_edges=limit_edges,
                collection_id=collection_id,
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/similarity/claims")
def similar_claims(paper_ids: str, min_score: float = 0.0, limit_per_source: int = 2, limit_total: int = 4000):
    try:
        ids = [s.strip() for s in str(paper_ids or "").split(",") if s.strip()]
        if not ids:
            raise HTTPException(status_code=400, detail="paper_ids is required (comma-separated)")
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return {
                "edges": client.list_similar_claim_edges_in_papers(
                    paper_ids=ids, min_score=float(min_score), limit_per_source=limit_per_source, limit_total=limit_total
                )
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/similarity/logic")
def similar_logic(paper_ids: str, min_score: float = 0.0, limit_per_source: int = 2, limit_total: int = 3000):
    try:
        ids = [s.strip() for s in str(paper_ids or "").split(",") if s.strip()]
        if not ids:
            raise HTTPException(status_code=400, detail="paper_ids is required (comma-separated)")
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            return {
                "edges": client.list_similar_logic_edges_in_papers(
                    paper_ids=ids, min_score=float(min_score), limit_per_source=limit_per_source, limit_total=limit_total
                )
            }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ResolveReferenceRequest(BaseModel):
    ref_id: str
    doi: str = Field(min_length=6)


@router.post("/resolve")
def resolve_reference(req: ResolveReferenceRequest):
    doi = req.doi.strip().lower()
    crossref = CrossrefClient()
    try:
        # If user provides a DOI, fetch metadata via Crossref to populate the cited Paper node.
        meta = crossref.get_work_by_doi(doi)
        cited_props = {
            "paper_id": f"doi:{doi}",
            "doi": doi,
            "title": meta.title if meta else None,
            "year": meta.year if meta else None,
            "venue": meta.venue if meta else None,
            "authors": meta.authors if meta else [],
        }
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            client.resolve_reference(ref_id=req.ref_id, cited_paper=cited_props)
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UpdateCitePurposeRequest(BaseModel):
    citing_paper_id: str
    cited_paper_id: str
    labels: list[str] = Field(min_length=1, max_length=3)
    scores: list[float] = Field(min_length=1, max_length=3)


@router.post("/cites/purpose")
def update_cite_purpose(req: UpdateCitePurposeRequest):
    if len(req.labels) != len(req.scores):
        raise HTTPException(status_code=400, detail="labels and scores length mismatch")
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            client.update_cites_purposes(
                citing_paper_id=req.citing_paper_id,
                cited_paper_id=req.cited_paper_id,
                labels=req.labels,
                scores=req.scores,
            )
        return {"ok": True}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
