from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.delete_assets import delete_paper_asset
from app.graph.neo4j_client import Neo4jClient
from app.schema_store import load_active, load_version, normalize_paper_type
from app.settings import settings
from app.tasks.manager import task_manager
from app.tasks.models import TaskType


router = APIRouter(prefix="/papers", tags=["papers"])

_WS_RE = re.compile(r"\s+")


def _norm_claim_text(text: str) -> str:
    s = _WS_RE.sub(" ", (text or "").strip())
    while s and s[-1] in ".;。；":
        s = s[:-1].rstrip()
    return s


def _claim_key_for(doi: str, text: str) -> str:
    base = (doi.strip().lower() + "\0" + _norm_claim_text(text)).encode("utf-8", errors="ignore")
    return hashlib.sha256(base).hexdigest()[:24]


def _safe_json(obj: object, default):  # type: ignore[no-untyped-def]
    if obj is None:
        return default
    if isinstance(obj, (dict, list)):
        return obj
    try:
        s = str(obj)
        if not s.strip():
            return default
        return json.loads(s)
    except Exception:
        return default


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _append_log(paper: dict, line: str) -> dict:
    log = list(paper.get("edit_log") or [])
    log.append(line)
    if len(log) > 200:
        log = log[-200:]
    return {"edit_log": log}


def _load_schema_for_paper(paper: dict) -> dict[str, Any]:
    pt = normalize_paper_type(paper.get("schema_paper_type") or paper.get("paper_type"))
    try:
        v = int(paper.get("schema_version") or 1)
        return load_version(pt, v)  # type: ignore[arg-type]
    except Exception:
        return load_active(pt)  # type: ignore[arg-type]


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _safe_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s)


class UpdateMetadataRequest(BaseModel):
    action: Literal["set", "use_machine", "clear"] = Field(default="set")
    title: str | None = None
    year: int | None = None
    fields: list[Literal["title", "year"]] | None = None


@router.patch("/{paper_id:path}/metadata")
def update_metadata(paper_id: str, req: UpdateMetadataRequest):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            paper = client.get_paper_basic(paper_id)
            human_meta = _safe_json(paper.get("human_meta_json"), {})
            cleared = set(_safe_json(paper.get("human_meta_cleared_json"), []))
            if not isinstance(human_meta, dict):
                human_meta = {}

            if req.action == "set":
                if req.title is not None:
                    human_meta["title"] = req.title
                    cleared.discard("title")
                if req.year is not None:
                    human_meta["year"] = int(req.year)
                    cleared.discard("year")
            elif req.action == "use_machine":
                fields = set(req.fields or [])
                if not fields:
                    # Back-compat: legacy clients send dummy "title/year" values to indicate fields.
                    if req.title is not None:
                        fields.add("title")
                    if req.year is not None:
                        fields.add("year")
                if not fields:
                    raise HTTPException(status_code=400, detail="fields required for action=use_machine")
                for f in fields:
                    human_meta.pop(f, None)
                    cleared.discard(f)
            elif req.action == "clear":
                fields = set(req.fields or [])
                if not fields:
                    # Back-compat: legacy clients send dummy "title/year" values to indicate fields.
                    if req.title is not None:
                        fields.add("title")
                    if req.year is not None:
                        fields.add("year")
                if not fields:
                    raise HTTPException(status_code=400, detail="fields required for action=clear")
                for f in fields:
                    human_meta.pop(f, None)
                    cleared.add(f)

            props = {
                "human_meta_json": _dump(human_meta),
                "human_meta_cleared_json": _dump(sorted(cleared)),
            }
            if req.action == "set":
                props.update(_append_log(paper, f"metadata:{req.action}"))
            else:
                props.update(_append_log(paper, f"metadata:{req.action}:{','.join(sorted(set(req.fields or []))) or 'legacy'}"))
            client.update_paper_props(paper_id, props)
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{paper_id:path}")
def delete_ingested_paper(paper_id: str, hard_delete: bool = True):
    """
    User-facing delete.

    hard_delete=true (default):
    - Delete owned subgraph + Paper node itself from Neo4j.
    - Remove collection links and all incident relationships.

    hard_delete=false:
    - Legacy behavior: keep Paper node as stub and clear ingest/editor state.

    In both modes:
    - Remove canonical storage (for DOI papers) and derived artifacts when safely resolvable.
    """
    try:
        return delete_paper_asset(paper_id, hard_delete=hard_delete)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UpdateLogicStepRequest(BaseModel):
    action: Literal["set", "use_machine", "clear"] = Field(default="set")
    summary: str | None = None


@router.patch("/{paper_id:path}/logic/{step_type}")
def update_logic_step(paper_id: str, step_type: str, req: UpdateLogicStepRequest):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            paper = client.get_paper_basic(paper_id)
            schema = _load_schema_for_paper(paper)
            step_ids = [str(s.get("id") or "") for s in (schema.get("steps") or [])]
            if step_type not in set(step_ids):
                raise HTTPException(status_code=400, detail=f"Invalid step_type: {step_type}")
            human_logic = _safe_json(paper.get("human_logic_json"), {})
            cleared = set(_safe_json(paper.get("human_logic_cleared_json"), []))
            if not isinstance(human_logic, dict):
                human_logic = {}

            if req.action == "set":
                human_logic[step_type] = (req.summary or "").strip()
                cleared.discard(step_type)
            elif req.action == "use_machine":
                human_logic.pop(step_type, None)
                cleared.discard(step_type)
            elif req.action == "clear":
                human_logic.pop(step_type, None)
                cleared.add(step_type)

            props = {
                "human_logic_json": _dump(human_logic),
                "human_logic_cleared_json": _dump(sorted(cleared)),
            }
            props.update(_append_log(paper, f"logic:{step_type}:{req.action}"))
            client.update_paper_props(paper_id, props)
        try:
            task_manager.submit(TaskType.update_similarity_paper, {"paper_id": paper_id})
        except Exception:
            pass
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UpsertClaimRequest(BaseModel):
    action: Literal["set", "use_machine", "clear"] = Field(default="set")
    text: str | None = None


class AddClaimRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/{paper_id:path}/claims")
def add_claim(paper_id: str, req: AddClaimRequest):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            paper = client.get_paper_basic(paper_id)
            doi = str(paper.get("doi") or "")
            if not doi and paper_id.startswith("doi:"):
                doi = paper_id[4:]
            if not doi:
                raise HTTPException(status_code=400, detail="Paper DOI missing; cannot derive claim_key")

            key = _claim_key_for(doi, req.text)
            human_claims = _safe_json(paper.get("human_claims_json"), {})
            cleared = set(_safe_json(paper.get("human_claims_cleared_json"), []))
            if not isinstance(human_claims, dict):
                human_claims = {}
            human_claims[key] = req.text.strip()
            cleared.discard(key)

            props = {
                "human_claims_json": _dump(human_claims),
                "human_claims_cleared_json": _dump(sorted(cleared)),
            }
            props.update(_append_log(paper, f"claim:add:{key}"))
            client.update_paper_props(paper_id, props)
            try:
                client.upsert_human_only_claim_node(paper_id=paper_id, claim_key=key, text=req.text.strip())
            except Exception:
                pass
        try:
            task_manager.submit(TaskType.update_similarity_paper, {"paper_id": paper_id})
        except Exception:
            pass
        return {"ok": True, "claim_key": key}
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.patch("/{paper_id:path}/claims/{claim_key}")
def upsert_claim(paper_id: str, claim_key: str, req: UpsertClaimRequest):
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            paper = client.get_paper_basic(paper_id)
            human_claims = _safe_json(paper.get("human_claims_json"), {})
            cleared = set(_safe_json(paper.get("human_claims_cleared_json"), []))
            if not isinstance(human_claims, dict):
                human_claims = {}

            if req.action == "set":
                human_claims[claim_key] = (req.text or "").strip()
                cleared.discard(claim_key)
                try:
                    client.upsert_human_only_claim_node(paper_id=paper_id, claim_key=claim_key, text=(req.text or "").strip())
                except Exception:
                    pass
            elif req.action == "use_machine":
                human_claims.pop(claim_key, None)
                cleared.discard(claim_key)
            elif req.action == "clear":
                human_claims.pop(claim_key, None)
                cleared.add(claim_key)

            props = {
                "human_claims_json": _dump(human_claims),
                "human_claims_cleared_json": _dump(sorted(cleared)),
            }
            props.update(_append_log(paper, f"claim:{claim_key}:{req.action}"))
            client.update_paper_props(paper_id, props)
        try:
            task_manager.submit(TaskType.update_similarity_paper, {"paper_id": paper_id})
        except Exception:
            pass
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


_TOKEN_RE = re.compile(r"[A-Za-z]+|\d+|[\u4e00-\u9fff]+")


def _tokens(s: str) -> list[str]:
    toks = _TOKEN_RE.findall((s or "").lower())
    out: list[str] = []
    for t in toks:
        if re.fullmatch(r"[\u4e00-\u9fff]+", t) and len(t) > 2:
            out.extend(list(t))
        else:
            out.append(t)
    return [t for t in out if t and t not in {"the", "and", "of", "to", "in", "a", "an"}]


@router.get("/{paper_id:path}/chunks/search")
def search_chunks(paper_id: str, q: str = "", limit: int = 50):
    """
    Lightweight chunk search to support evidence selection UI.
    """
    try:
        query = (q or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="q is required")
        limit = max(1, min(200, int(limit)))
        toks = _tokens(query)
        if not toks:
            toks = [query.lower()]
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            rows = client.list_chunks_for_paper(paper_id, limit=8000)
        scored: list[tuple[float, dict]] = []
        for r in rows:
            text = str(r.get("text") or "").lower()
            if not text:
                continue
            s = 0.0
            for t in toks:
                cnt = text.count(t)
                if cnt:
                    s += 1.0 + min(5, cnt) * 0.3
            if s > 0:
                scored.append((s, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for score, r in scored[:limit]:
            raw_txt = str(r.get("text") or "").strip()
            snippet = raw_txt.replace("\n", " ")
            snippet = _WS_RE.sub(" ", snippet)[:800]
            full = raw_txt[:4000]
            out.append(
                {
                    "chunk_id": r.get("chunk_id"),
                    "section": r.get("section"),
                    "kind": r.get("kind"),
                    "start_line": r.get("start_line"),
                    "end_line": r.get("end_line"),
                    "score": float(score),
                    "snippet": snippet,
                    "text": full,
                    "text_truncated": bool(len(raw_txt) > len(full)),
                }
            )
        return {"chunks": out}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UpdateClaimEvidenceRequest(BaseModel):
    action: Literal["set", "use_machine", "clear"] = Field(default="set")
    chunk_ids: list[str] = Field(default_factory=list)


@router.patch("/{paper_id:path}/claims/{claim_key}/evidence")
def update_claim_evidence(paper_id: str, claim_key: str, req: UpdateClaimEvidenceRequest):
    """
    Persist human evidence selection on the Paper node, and apply it to current Claim->Chunk edges.
    Human evidence persists across rebuild (since Paper node is preserved).
    """
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            paper = client.get_paper_basic(paper_id)
            evidence = _safe_json(paper.get("human_claim_evidence_json"), {})
            cleared = set(_safe_json(paper.get("human_claim_evidence_cleared_json"), []))
            if not isinstance(evidence, dict):
                evidence = {}

            if req.action == "set":
                ids = [str(x).strip() for x in (req.chunk_ids or []) if str(x).strip()]
                evidence[str(claim_key)] = ids
                cleared.discard(str(claim_key))
                client.set_claim_evidence(paper_id, claim_key, ids, source="human")
            elif req.action == "use_machine":
                evidence.pop(str(claim_key), None)
                cleared.discard(str(claim_key))
                client.set_claim_evidence(paper_id, claim_key, [], source="human")
            elif req.action == "clear":
                evidence.pop(str(claim_key), None)
                cleared.add(str(claim_key))
                client.set_claim_evidence(paper_id, claim_key, [], source="human")

            props = {
                "human_claim_evidence_json": _dump(evidence),
                "human_claim_evidence_cleared_json": _dump(sorted(cleared)),
            }
            props.update(_append_log(paper, f"claim_evidence:{claim_key}:{req.action}"))
            client.update_paper_props(paper_id, props)
        return {"ok": True}
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class UpdateLogicStepEvidenceRequest(BaseModel):
    action: Literal["set", "use_machine", "clear"] = Field(default="set")
    chunk_ids: list[str] = Field(default_factory=list)


@router.patch("/{paper_id:path}/logic_steps/{step_type}/evidence")
def update_logic_step_evidence(paper_id: str, step_type: str, req: UpdateLogicStepEvidenceRequest):
    """
    Persist human evidence selection for a LogicStep on the Paper node, and apply it to current LogicStep->Chunk edges.
    Human evidence persists across rebuild (Paper node is preserved).
    """
    try:
        st = str(step_type or "").strip()
        if not st:
            raise HTTPException(status_code=400, detail="step_type required")
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            paper = client.get_paper_basic(paper_id)
            schema = _load_schema_for_paper(paper)
            allowed_steps = {str(s.get("id") or "") for s in (schema.get("steps") or []) if str(s.get("id") or "").strip()}
            if allowed_steps and st not in allowed_steps:
                raise HTTPException(status_code=400, detail=f"Unknown step_type for this paper schema: {st}")

            evidence = _safe_json(paper.get("human_logic_evidence_json"), {})
            cleared = set(_safe_json(paper.get("human_logic_evidence_cleared_json"), []))
            if not isinstance(evidence, dict):
                evidence = {}

            ids = [str(x).strip() for x in (req.chunk_ids or []) if str(x).strip()]

            if req.action == "set":
                evidence[st] = ids
                cleared.discard(st)
                client.set_logic_step_evidence(paper_id, st, ids, source="human")
            elif req.action == "use_machine":
                evidence.pop(st, None)
                cleared.discard(st)
                client.set_logic_step_evidence(paper_id, st, [], source="human")
            elif req.action == "clear":
                evidence.pop(st, None)
                cleared.add(st)
                client.set_logic_step_evidence(paper_id, st, [], source="human")

            props = {
                "human_logic_evidence_json": _dump(evidence),
                "human_logic_evidence_cleared_json": _dump(sorted(cleared)),
            }
            props.update(_append_log(paper, f"logic_evidence:{st}:{req.action}"))
            client.update_paper_props(paper_id, props)
        return {"ok": True}
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

class UpdateCitePurposeRequest(BaseModel):
    action: Literal["set", "use_machine", "clear"] = Field(default="set")
    labels: list[str] | None = None
    scores: list[float] | None = None


@router.patch("/{paper_id:path}/cites/{cited_paper_id:path}/purpose")
def update_cite_purpose(paper_id: str, cited_paper_id: str, req: UpdateCitePurposeRequest):
    try:
        if req.action == "set":
            labels = list(req.labels or [])
            scores = list(req.scores or [])
            if len(labels) != len(scores):
                raise HTTPException(status_code=400, detail="labels and scores length mismatch")
            if not (1 <= len(labels) <= 3):
                raise HTTPException(status_code=400, detail="labels must be 1..3")
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            paper = client.get_paper_basic(paper_id)
            human_cites = _safe_json(paper.get("human_cites_purpose_json"), {})
            cleared = set(_safe_json(paper.get("human_cites_purpose_cleared_json"), []))
            if not isinstance(human_cites, dict):
                human_cites = {}

            if req.action == "set":
                human_cites[cited_paper_id] = {"labels": labels, "scores": scores}
                cleared.discard(cited_paper_id)
            elif req.action == "use_machine":
                human_cites.pop(cited_paper_id, None)
                cleared.discard(cited_paper_id)
            elif req.action == "clear":
                human_cites.pop(cited_paper_id, None)
                cleared.add(cited_paper_id)

            props = {
                "human_cites_purpose_json": _dump(human_cites),
                "human_cites_purpose_cleared_json": _dump(sorted(cleared)),
            }
            props.update(_append_log(paper, f"cite:{cited_paper_id}:{req.action}"))
            client.update_paper_props(paper_id, props)
        return {"ok": True}
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ReviewDecision(BaseModel):
    kind: Literal["meta_title", "meta_year", "logic_step", "claim", "cite_purpose"]
    key: str
    decision: Literal["keep_human", "use_machine", "clear"]


class ApplyReviewRequest(BaseModel):
    decisions: list[ReviewDecision] = Field(default_factory=list)


@router.post("/{paper_id:path}/review/apply")
def apply_review(paper_id: str, req: ApplyReviewRequest):
    """
    Apply review decisions and mark the current pending rebuild as resolved.
    Decisions only affect Paper-level human overrides/clears; machine graph stays intact.
    """
    try:
        with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
            paper = client.get_paper_basic(paper_id)
            human_meta = _safe_json(paper.get("human_meta_json"), {})
            meta_cleared = set(_safe_json(paper.get("human_meta_cleared_json"), []))
            human_logic = _safe_json(paper.get("human_logic_json"), {})
            logic_cleared = set(_safe_json(paper.get("human_logic_cleared_json"), []))
            human_claims = _safe_json(paper.get("human_claims_json"), {})
            claims_cleared = set(_safe_json(paper.get("human_claims_cleared_json"), []))
            human_cites = _safe_json(paper.get("human_cites_purpose_json"), {})
            cites_cleared = set(_safe_json(paper.get("human_cites_purpose_cleared_json"), []))

            if not isinstance(human_meta, dict):
                human_meta = {}
            if not isinstance(human_logic, dict):
                human_logic = {}
            if not isinstance(human_claims, dict):
                human_claims = {}
            if not isinstance(human_cites, dict):
                human_cites = {}

            for d in req.decisions:
                if d.kind == "meta_title":
                    if d.decision == "use_machine":
                        human_meta.pop("title", None)
                        meta_cleared.discard("title")
                    elif d.decision == "clear":
                        human_meta.pop("title", None)
                        meta_cleared.add("title")
                elif d.kind == "meta_year":
                    if d.decision == "use_machine":
                        human_meta.pop("year", None)
                        meta_cleared.discard("year")
                    elif d.decision == "clear":
                        human_meta.pop("year", None)
                        meta_cleared.add("year")
                elif d.kind == "logic_step":
                    step = d.key
                    if d.decision == "use_machine":
                        human_logic.pop(step, None)
                        logic_cleared.discard(step)
                    elif d.decision == "clear":
                        human_logic.pop(step, None)
                        logic_cleared.add(step)
                elif d.kind == "claim":
                    key = d.key
                    if d.decision == "use_machine":
                        human_claims.pop(key, None)
                        claims_cleared.discard(key)
                    elif d.decision == "clear":
                        human_claims.pop(key, None)
                        claims_cleared.add(key)
                elif d.kind == "cite_purpose":
                    cited = d.key
                    if d.decision == "use_machine":
                        human_cites.pop(cited, None)
                        cites_cleared.discard(cited)
                    elif d.decision == "clear":
                        human_cites.pop(cited, None)
                        cites_cleared.add(cited)

            pending = str(paper.get("review_pending_task_id") or "")
            props = {
                "human_meta_json": _dump(human_meta),
                "human_meta_cleared_json": _dump(sorted(meta_cleared)),
                "human_logic_json": _dump(human_logic),
                "human_logic_cleared_json": _dump(sorted(logic_cleared)),
                "human_claims_json": _dump(human_claims),
                "human_claims_cleared_json": _dump(sorted(claims_cleared)),
                "human_cites_purpose_json": _dump(human_cites),
                "human_cites_purpose_cleared_json": _dump(sorted(cites_cleared)),
                "review_resolved_task_id": pending,
            }
            props.update(_append_log(paper, f"review:apply:{len(req.decisions)}"))
            client.update_paper_props(paper_id, props)
        return {"ok": True}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
