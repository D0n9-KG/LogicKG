from __future__ import annotations

import json
import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from neo4j import GraphDatabase

from app.citations.models import derive_polarity, derive_semantic_signals, derive_target_scopes
from app.graph.textbook_graph import build_community_rows, sample_connected_graph_rows
from app.ingest.models import DocumentIR
from app.settings import settings


def _paper_id_for_doc(doc: DocumentIR) -> str:
    return paper_id_for_md_path(doc.paper.md_path, doi=doc.paper.doi)


def paper_id_for_md_path(md_path: str, doi: str | None = None) -> str:
    if doi:
        return f"doi:{doi.strip().lower()}"
    h = hashlib.sha256()
    h.update(md_path.encode("utf-8", errors="ignore"))
    return h.hexdigest()


_WS_RE = re.compile(r"\s+")


def _safe_storage_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or ""))


def _author_id_for_name(name: str) -> str:
    normalized = _WS_RE.sub(" ", str(name or "").strip()).lower()
    if not normalized:
        return ""
    digest = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()[:24]
    return f"author:{digest}"


def _read_json_list(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _citation_enrichment_artifact_dir(paper_id: str) -> Path:
    return Path(str(settings.storage_dir or "backend/storage")) / "derived" / "papers" / _safe_storage_id(paper_id)


def _load_citation_enrichment_artifacts(paper_id: str) -> tuple[list[dict], list[dict]]:
    artifact_dir = _citation_enrichment_artifact_dir(paper_id)
    return (
        _read_json_list(artifact_dir / "citation_acts.json"),
        _read_json_list(artifact_dir / "citation_mentions.json"),
    )


def _norm_string_list(values: object) -> list[str]:
    out: list[str] = []
    for item in values if isinstance(values, list) else []:
        value = str(item or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _norm_float_list(values: object) -> list[float]:
    out: list[float] = []
    for item in values if isinstance(values, list) else []:
        try:
            out.append(float(item))
        except Exception:
            out.append(0.0)
    return out


def _sort_citation_mentions(mentions: list[dict]) -> list[dict]:
    return sorted(
        mentions,
        key=lambda item: (
            int(item.get("ref_num") or 0),
            int(item.get("span_start") or 0),
            int(item.get("span_end") or 0),
            str(item.get("source_chunk_id") or ""),
            str(item.get("mention_id") or ""),
        ),
    )


def _merge_outgoing_citation_enrichment(
    *,
    outgoing_raw: list[dict],
    human_cites: dict | list | None,
    cites_cleared: set[str],
    needs_review: bool,
    citation_acts: list[dict] | None,
    citation_mentions: list[dict] | None,
) -> list[dict]:
    act_by_cited: dict[str, dict] = {}
    for item in citation_acts or []:
        cited_paper_id = str(item.get("cited_paper_id") or "").strip()
        if cited_paper_id:
            act_by_cited[cited_paper_id] = dict(item)

    mentions_by_cited: dict[str, list[dict]] = defaultdict(list)
    for item in citation_mentions or []:
        cited_paper_id = str(item.get("cited_paper_id") or "").strip()
        if not cited_paper_id:
            continue
        mentions_by_cited[cited_paper_id].append(
            {
                "mention_id": str(item.get("mention_id") or "").strip(),
                "ref_num": int(item.get("ref_num") or 0),
                "source_chunk_id": str(item.get("source_chunk_id") or "").strip(),
                "span_start": int(item.get("span_start") or 0),
                "span_end": int(item.get("span_end") or 0),
                "section": str(item.get("section") or "").strip() or "unknown",
                "context_text": str(item.get("context_text") or "").strip(),
                "target_scopes": _norm_string_list(item.get("target_scopes")),
            }
        )

    outgoing: list[dict] = []
    for raw in outgoing_raw:
        cited_id = str(raw.get("cited_paper_id") or "").strip()
        machine_labels = _norm_string_list(raw.get("purpose_labels"))
        machine_scores = _norm_float_list(raw.get("purpose_scores"))
        human = human_cites.get(cited_id) if isinstance(human_cites, dict) else None
        cleared = cited_id in cites_cleared
        if cleared:
            labels: list[str] = []
            scores: list[float] = []
            source = "cleared"
            human_labels = None
            human_scores = None
        elif isinstance(human, dict) and human.get("labels") is not None:
            labels = _norm_string_list(human.get("labels"))
            scores = _norm_float_list(human.get("scores"))
            source = "human"
            human_labels = labels
            human_scores = scores
        else:
            labels = machine_labels
            scores = machine_scores
            source = "machine"
            human_labels = None
            human_scores = None

        act = act_by_cited.get(cited_id, {})
        semantic = {
            "polarity": derive_polarity(labels, scores),
            "semantic_signals": derive_semantic_signals(labels, scores),
            "target_scopes": derive_target_scopes(labels),
            "evidence_chunk_ids": _norm_string_list(act.get("evidence_chunk_ids") or raw.get("evidence_chunk_ids")),
            "evidence_spans": _norm_string_list(act.get("evidence_spans") or raw.get("evidence_spans")),
        }

        out = dict(raw)
        out["purpose_labels_machine"] = machine_labels
        out["purpose_scores_machine"] = machine_scores
        out["purpose_labels_human"] = human_labels
        out["purpose_scores_human"] = human_scores
        out["purpose_source"] = source
        out["purpose_labels"] = labels
        out["purpose_scores"] = scores
        out["semantic"] = semantic
        out["mentions"] = _sort_citation_mentions(mentions_by_cited.get(cited_id, []))
        if needs_review and source in {"human", "cleared"}:
            out["pending_machine_purpose_labels"] = machine_labels
            out["pending_machine_purpose_scores"] = machine_scores
        outgoing.append(out)
    return outgoing


def iso_time_for_paper_year(year: int | None) -> str:
    try:
        y = int(year) if year is not None else None
    except Exception:
        y = None
    if y is None or y < 1000 or y > 9999:
        return datetime.now(tz=timezone.utc).isoformat()
    return datetime(y, 1, 1, tzinfo=timezone.utc).isoformat()


def _split_prefixed_evidence_ids(ids: list[str]) -> dict[str, list[str]]:
    out = {
        "claim_ids": [],
        "community_ids": [],
        "chunk_ids": [],
        "event_ids": [],
        "other_ids": [],
    }
    seen = {k: set() for k in out}
    for raw in ids or []:
        value = str(raw or "").strip()
        if not value:
            continue
        if ":" in value:
            prefix, payload = value.split(":", 1)
            key = prefix.strip().upper()
            payload = payload.strip()
        else:
            key, payload = "", value
        bucket = "other_ids"
        if key == "CL":
            bucket = "claim_ids"
        elif key == "GC":
            bucket = "community_ids"
        elif key == "CH":
            bucket = "chunk_ids"
        elif key == "EV":
            bucket = "event_ids"
        if payload and payload not in seen[bucket]:
            seen[bucket].add(payload)
            out[bucket].append(payload)
    return out


def _local_louvain_partition(nodes: list[str], edges: list[tuple[str, str, float]], max_iter: int = 24) -> dict[str, int]:
    """Lightweight local-moving Louvain phase for small in-memory graphs."""
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
    ordered_comms = sorted(
        comm_to_nodes.items(),
        key=lambda x: (-len(x[1]), min(x[1])),
    )
    remap = {old: idx for idx, (old, _) in enumerate(ordered_comms)}
    return {nid: remap[int(comm)] for nid, comm in part.items()}


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str):
        try:
            connect_timeout = float(getattr(settings, "neo4j_connection_timeout_seconds", 15.0) or 15.0)
        except Exception:
            connect_timeout = 15.0
        connect_timeout = max(1.0, min(120.0, connect_timeout))

        self._driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=connect_timeout)

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "Neo4jClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        self.close()

    def ensure_schema(self) -> None:
        stmts = [
            "CREATE CONSTRAINT paper_id_unique IF NOT EXISTS FOR (p:Paper) REQUIRE p.paper_id IS UNIQUE",
            "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:Chunk) REQUIRE c.chunk_id IS UNIQUE",
            "CREATE CONSTRAINT ref_id_unique IF NOT EXISTS FOR (r:ReferenceEntry) REQUIRE r.ref_id IS UNIQUE",
            "CREATE CONSTRAINT logic_step_id_unique IF NOT EXISTS FOR (s:LogicStep) REQUIRE s.logic_step_id IS UNIQUE",
            "CREATE CONSTRAINT claim_id_unique IF NOT EXISTS FOR (cl:Claim) REQUIRE cl.claim_id IS UNIQUE",
            "CREATE CONSTRAINT evidence_event_id_unique IF NOT EXISTS FOR (ev:EvidenceEvent) REQUIRE ev.event_id IS UNIQUE",
            "CREATE CONSTRAINT figure_id_unique IF NOT EXISTS FOR (f:Figure) REQUIRE f.figure_id IS UNIQUE",
            "CREATE CONSTRAINT collection_id_unique IF NOT EXISTS FOR (co:Collection) REQUIRE co.collection_id IS UNIQUE",
            "CREATE CONSTRAINT author_id_unique IF NOT EXISTS FOR (a:Author) REQUIRE a.author_id IS UNIQUE",
            "CREATE INDEX paper_doi IF NOT EXISTS FOR (p:Paper) ON (p.doi)",
            "CREATE INDEX paper_year IF NOT EXISTS FOR (p:Paper) ON (p.year)",
            "CREATE INDEX paper_ingested IF NOT EXISTS FOR (p:Paper) ON (p.ingested)",
            "CREATE INDEX author_name IF NOT EXISTS FOR (a:Author) ON (a.name)",
            "CREATE INDEX evidence_event_type IF NOT EXISTS FOR (ev:EvidenceEvent) ON (ev.event_type)",
            "CREATE INDEX evidence_event_status IF NOT EXISTS FOR (ev:EvidenceEvent) ON (ev.status)",
            "CREATE INDEX collection_name IF NOT EXISTS FOR (co:Collection) ON (co.name)",
            # 鈹€鈹€ Textbook sub-graph constraints & indexes 鈹€鈹€
            "CREATE CONSTRAINT textbook_id_unique IF NOT EXISTS FOR (t:Textbook) REQUIRE t.textbook_id IS UNIQUE",
            "CREATE CONSTRAINT chapter_id_unique IF NOT EXISTS FOR (tc:TextbookChapter) REQUIRE tc.chapter_id IS UNIQUE",
            "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (ke:KnowledgeEntity) REQUIRE ke.entity_id IS UNIQUE",
            "CREATE CONSTRAINT global_community_id_unique IF NOT EXISTS FOR (gc:GlobalCommunity) REQUIRE gc.community_id IS UNIQUE",
            "CREATE CONSTRAINT global_keyword_id_unique IF NOT EXISTS FOR (gk:GlobalKeyword) REQUIRE gk.keyword_id IS UNIQUE",
            "CREATE INDEX entity_name IF NOT EXISTS FOR (ke:KnowledgeEntity) ON (ke.name)",
            "CREATE INDEX entity_type IF NOT EXISTS FOR (ke:KnowledgeEntity) ON (ke.entity_type)",
            "CREATE INDEX global_community_version IF NOT EXISTS FOR (gc:GlobalCommunity) ON (gc.version)",
            "CREATE INDEX global_keyword_text IF NOT EXISTS FOR (gk:GlobalKeyword) ON (gk.keyword)",
        ]
        with self._driver.session() as session:
            for s in stmts:
                session.run(s)

    def drop_legacy_proposition_schema(self) -> dict[str, int]:
        constraints = [
            "DROP CONSTRAINT proposition_id_unique IF EXISTS",
            "DROP CONSTRAINT proposition_key_unique IF EXISTS",
            "DROP CONSTRAINT proposition_group_id_unique IF EXISTS",
        ]
        indexes = [
            "DROP INDEX proposition_state IF EXISTS",
            "DROP INDEX proposition_score IF EXISTS",
        ]
        with self._driver.session() as session:
            for stmt in constraints + indexes:
                session.run(stmt)
        return {
            "dropped_constraints": len(constraints),
            "dropped_indexes": len(indexes),
        }

    def drop_legacy_discovery_schema(self) -> dict[str, int]:
        constraints = [
            "DROP CONSTRAINT rq_candidate_id_unique IF EXISTS",
            "DROP CONSTRAINT feedback_id_unique IF EXISTS",
            "DROP CONSTRAINT knowledge_gap_id_unique IF EXISTS",
            "DROP CONSTRAINT research_question_id_unique IF EXISTS",
            "DROP CONSTRAINT knowledge_gap_seed_id_unique IF EXISTS",
        ]
        indexes = [
            "DROP INDEX rq_status IF EXISTS",
            "DROP INDEX rq_quality_score IF EXISTS",
            "DROP INDEX feedback_candidate_id IF EXISTS",
            "DROP INDEX knowledge_gap_domain IF EXISTS",
            "DROP INDEX knowledge_gap_type IF EXISTS",
            "DROP INDEX research_question_domain IF EXISTS",
            "DROP INDEX research_question_status IF EXISTS",
            "DROP INDEX research_question_quality IF EXISTS",
            "DROP INDEX knowledge_gap_seed_kinds IF EXISTS",
        ]
        with self._driver.session() as session:
            for stmt in constraints + indexes:
                session.run(stmt)
        return {
            "dropped_constraints": len(constraints),
            "dropped_indexes": len(indexes),
        }

    def upsert_paper_and_chunks(self, doc: DocumentIR) -> None:
        paper_id = _paper_id_for_doc(doc)
        storage_dir = None
        try:
            md_parent = Path(doc.paper.md_path).resolve().parent
            # backend/storage/papers/doi/<...>
            root = Path(__file__).resolve().parents[2] / settings.storage_dir / "papers" / "doi"
            if md_parent.is_dir() and str(md_parent).lower().startswith(str(root).lower()):
                storage_dir = str(md_parent)
        except Exception:
            storage_dir = None
        paper_props = {
            "paper_id": paper_id,
            "paper_source": doc.paper.paper_source,
            "source_md_path": doc.paper.md_path,
            "storage_dir": storage_dir,
            "title": doc.paper.title,
            "title_alt": doc.paper.title_alt,
            "doi": doc.paper.doi,
            "year": doc.paper.year,
            "authors": doc.paper.authors,
            "ingested": True,
            # If this Paper previously existed as a stub (cited-only) or was user-deleted,
            # clear deletion markers now that we are ingesting full content again.
            "deleted_at": None,
            "deleted_reason": None,
        }
        chunks = [
            {
                "chunk_id": c.chunk_id,
                "paper_id": paper_id,
                "md_path": c.md_path,
                "start_line": c.span.start_line,
                "end_line": c.span.end_line,
                "section": c.section,
                "kind": c.kind,
                "text": c.text,
            }
            for c in doc.chunks
        ]
        seen_authors: set[str] = set()
        authors: list[dict] = []
        for raw in list(doc.paper.authors or []):
            name = str(raw or "").strip()
            if not name:
                continue
            author_id = _author_id_for_name(name)
            if not author_id or author_id in seen_authors:
                continue
            seen_authors.add(author_id)
            authors.append({"author_id": author_id, "name": name})
        now = datetime.now(tz=timezone.utc).isoformat()
        cypher = """
MERGE (p:Paper {paper_id: $paper.paper_id})
SET p += $paper
WITH p
UNWIND $chunks AS c
MERGE (ch:Chunk {chunk_id: c.chunk_id})
SET ch += c
MERGE (p)-[:HAS_CHUNK]->(ch)
"""
        with self._driver.session() as session:
            session.run(cypher, paper=paper_props, chunks=chunks)
            if authors:
                session.run(
                    """
MATCH (p:Paper {paper_id:$paper_id})
WITH p, $authors AS authors
UNWIND authors AS a
MERGE (au:Author {author_id: a.author_id})
ON CREATE SET au.created_at = $now
SET au.name = a.name,
    au.name_norm = toLower(a.name),
    au.updated_at = $now
MERGE (au)-[:AUTHORED]->(p)
WITH collect(DISTINCT au) AS author_nodes
UNWIND range(0, size(author_nodes)-2) AS i
UNWIND range(i+1, size(author_nodes)-1) AS j
WITH author_nodes[i] AS a, author_nodes[j] AS b
MERGE (a)-[r1:CO_AUTHOR]->(b)
ON CREATE SET r1.created_at = $now, r1.weight = 0
SET r1.weight = coalesce(r1.weight, 0) + 1,
    r1.updated_at = $now
MERGE (b)-[r2:CO_AUTHOR]->(a)
ON CREATE SET r2.created_at = $now, r2.weight = 0
SET r2.weight = coalesce(r2.weight, 0) + 1,
    r2.updated_at = $now
""",
                    paper_id=paper_id,
                    authors=authors,
                    now=now,
                )

    def upsert_logic_steps_and_claims(self, paper_id: str, logic: dict, claims: list[dict], step_order: list[str] | None = None) -> None:
        """
        Upsert logic steps and claims (schema-driven).

        Required for each claim:
        - claim_id, claim_key, text, confidence, step_type

        Optional:
        - kinds: list[str]
        - evidence_chunk_ids: list[str]
        - evidence_weak: bool
        - targets_paper_ids: list[str]
        """
        if step_order is None:
            # Prefer stable order from caller; otherwise use keys order with deterministic fallback.
            step_order = list((logic or {}).keys())
        steps = []
        for idx, step_type in enumerate(step_order):
            v = (logic or {}).get(step_type) or {}

            # P0 Fix: Defensive filter - skip empty logic steps
            summary = v.get("summary") or ""
            evidence_ids = list(v.get("evidence_chunk_ids") or [])

            # Skip if both summary and evidence are empty
            if not summary.strip() and not evidence_ids:
                continue

            steps.append(
                {
                    "logic_step_id": f"{paper_id}:{step_type}",
                    "paper_id": paper_id,
                    "step_type": step_type,
                    "order": int(v.get("order") if v.get("order") is not None else idx),
                    "summary": summary,
                    "confidence": v.get("confidence"),
                    "evidence_chunk_ids": evidence_ids,
                    "evidence_weak": bool(v.get("evidence_weak") or False),
                }
            )
        cypher = """
MATCH (p:Paper {paper_id:$paper_id})
WITH p, $steps AS steps
CALL {
    WITH p, steps
    UNWIND steps AS s
    MERGE (ls:LogicStep {logic_step_id: s.logic_step_id})
    SET ls.paper_id = s.paper_id,
        ls.step_type = s.step_type,
        ls.order = s.order,
        ls.summary = s.summary,
        ls.confidence = s.confidence
    MERGE (p)-[:HAS_LOGIC_STEP]->(ls)
    RETURN count(*) AS logic_steps_written
}
CALL {
    WITH steps
    UNWIND range(0, size(steps)-2) AS i
    MATCH (a:LogicStep {logic_step_id: steps[i].logic_step_id})
    MATCH (b:LogicStep {logic_step_id: steps[i+1].logic_step_id})
    MERGE (a)-[:NEXT]->(b)
    RETURN count(*) AS next_edges_written
}
CALL {
    WITH steps
    UNWIND steps AS s
    MATCH (ls:LogicStep {logic_step_id: s.logic_step_id})
    WITH ls, s
    UNWIND coalesce(s.evidence_chunk_ids, []) AS cid
    MATCH (ch:Chunk {chunk_id: cid})
    MERGE (ls)-[e:EVIDENCED_BY {source:'machine'}]->(ch)
    SET e.weak = coalesce(s.evidence_weak, false)
    RETURN count(*) AS logic_step_evidence_written
}
WITH p
UNWIND $claims AS c
MERGE (cl:Claim {claim_id: c.claim_id})
SET cl.paper_id = $paper_id,
    cl.claim_key = coalesce(c.claim_key, c.claim_id),
    cl.text = c.text,
    cl.confidence = c.confidence,
    cl.step_type = c.step_type,
    cl.kinds = coalesce(c.kinds, []),
    cl.evidence_weak = coalesce(c.evidence_weak, false),
    cl.targets_paper_ids = coalesce(c.targets_paper_ids, []),
    cl.evidence_span_start = coalesce(c.span_start, -1),
    cl.evidence_span_end = coalesce(c.span_end, -1),
    cl.evidence_quote = coalesce(c.evidence_quote, ''),
    cl.match_mode = coalesce(c.match_mode, 'none'),
    cl.match_confidence = coalesce(c.match_confidence, 0.0)
MERGE (p)-[:HAS_CLAIM]->(cl)
WITH cl, c, $paper_id AS paper_id
OPTIONAL MATCH (ls:LogicStep {logic_step_id: paper_id + ':' + c.step_type})
FOREACH (_ IN CASE WHEN ls IS NULL THEN [] ELSE [1] END |
    MERGE (ls)-[:HAS_CLAIM]->(cl)
)
WITH cl, c
CALL {
    WITH cl, c
    UNWIND coalesce(c.evidence_chunk_ids, []) AS cid
    MATCH (ch:Chunk {chunk_id: cid})
    MERGE (cl)-[e:EVIDENCED_BY {source:'machine'}]->(ch)
    SET e.weak = coalesce(c.evidence_weak, false)
    RETURN count(*) AS claim_evidence_written
}
CALL {
    WITH cl, c
    UNWIND coalesce(c.targets_paper_ids, []) AS tid
    MATCH (tp:Paper {paper_id: tid})
    MERGE (cl)-[:TARGETS_PAPER]->(tp)
    RETURN count(*) AS claim_targets_written
}
RETURN count(*) AS claims_written
"""
        with self._driver.session() as session:
            session.run(cypher, paper_id=paper_id, steps=steps, claims=claims)

    def set_logic_step_evidence(self, paper_id: str, step_type: str, chunk_ids: list[str], source: str = "human") -> None:
        src = (source or "human").strip().lower()
        if src not in {"human", "machine"}:
            src = "human"
        st = str(step_type or "").strip()
        if not st:
            return
        cypher = """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_LOGIC_STEP]->(ls:LogicStep)
WHERE ls.step_type = $step_type
OPTIONAL MATCH (ls)-[e:EVIDENCED_BY]->(:Chunk)
WHERE coalesce(e.source,'machine') = $source
DELETE e
WITH ls
UNWIND $chunk_ids AS cid
MATCH (ch:Chunk {chunk_id: cid})
MERGE (ls)-[e:EVIDENCED_BY {source:$source}]->(ch)
SET e.weak = false
"""
        with self._driver.session() as session:
            session.run(cypher, paper_id=paper_id, step_type=st, chunk_ids=list(chunk_ids or []), source=src)

    def apply_human_logic_step_evidence_overrides(self, paper_id: str) -> None:
        """
        Re-apply Paper-level human evidence overrides for logic steps after rebuild/replace.
        """
        paper = self.get_paper_basic(paper_id)

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

        evidence = _safe_json(paper.get("human_logic_evidence_json"), {})
        cleared = set(_safe_json(paper.get("human_logic_evidence_cleared_json"), []))
        if not isinstance(evidence, dict):
            evidence = {}

        for step, ids in evidence.items():
            st = str(step)
            if not st:
                continue
            chunk_ids = [str(x).strip() for x in (ids or []) if str(x).strip()]
            self.set_logic_step_evidence(paper_id, st, chunk_ids, source="human")
        for st in cleared:
            self.set_logic_step_evidence(paper_id, str(st), [], source="human")

    def upsert_references_and_citations(
        self,
        paper_id: str,
        refs: list[dict],
        cited_papers: list[dict],
        cites_resolved: list[dict],
        cites_unresolved: list[dict],
    ) -> None:
        cypher = """
MATCH (p:Paper {paper_id: $paper_id})
CALL {
    WITH p
    UNWIND $refs AS r
    MERGE (re:ReferenceEntry {ref_id: r.ref_id})
    SET re += r
    MERGE (p)-[:HAS_REFERENCE]->(re)
    RETURN count(*) AS refs_written
}
CALL {
    WITH p
    UNWIND $cited_papers AS cp
    MERGE (q:Paper {paper_id: cp.paper_id})
    ON CREATE SET q += cp
    ON MATCH SET
        q.paper_id = cp.paper_id,
        q.doi = CASE
            WHEN cp.doi IS NULL OR trim(toString(cp.doi)) = '' THEN q.doi
            ELSE cp.doi
        END,
        q.title = coalesce(q.title, cp.title),
        q.authors = coalesce(q.authors, cp.authors),
        q.year = coalesce(q.year, cp.year),
        q.abstract = coalesce(q.abstract, cp.abstract),
        q.paper_source = coalesce(q.paper_source, cp.paper_source),
        q.md_path = coalesce(q.md_path, cp.md_path)
    RETURN count(*) AS cited_papers_written
}
CALL {
    WITH p
    UNWIND $cites_resolved AS cr
    MATCH (q:Paper {paper_id: cr.cited_paper_id})
    MERGE (p)-[c:CITES]->(q)
    SET c.total_mentions = cr.total_mentions,
        c.ref_nums = cr.ref_nums,
        c.evidence_chunk_ids = cr.evidence_chunk_ids,
        c.evidence_spans = cr.evidence_spans,
        c.purpose_labels = CASE
            WHEN c.purpose_labels IS NULL OR size(c.purpose_labels) = 0 THEN ['Background']
            ELSE c.purpose_labels
        END,
        c.purpose_scores = CASE
            WHEN c.purpose_scores IS NULL OR size(c.purpose_scores) = 0 THEN [0.2]
            ELSE c.purpose_scores
        END
    RETURN count(*) AS cites_resolved_written
}
CALL {
    WITH p
    UNWIND $cites_unresolved AS cu
    MATCH (re:ReferenceEntry {ref_id: cu.ref_id})
    MERGE (p)-[u:CITES_UNRESOLVED]->(re)
    SET u.total_mentions = cu.total_mentions,
        u.ref_nums = cu.ref_nums,
        u.evidence_chunk_ids = cu.evidence_chunk_ids,
        u.evidence_spans = cu.evidence_spans
    RETURN count(*) AS cites_unresolved_written
}
RETURN p.paper_id AS paper_id
"""
        with self._driver.session() as session:
            session.run(
                cypher,
                paper_id=paper_id,
                refs=refs,
                cited_papers=cited_papers,
                cites_resolved=cites_resolved,
                cites_unresolved=cites_unresolved,
            )

    def get_citation_context_by_paper_source(self, paper_sources: list[str], limit: int = 50) -> list[dict]:
        cypher = """
MATCH (p:Paper)
WHERE p.paper_source IN $paper_sources
OPTIONAL MATCH (p)-[c:CITES]->(q:Paper)
RETURN p.paper_source AS paper_source,
       p.doi AS doi,
       q.doi AS cited_doi,
       q.title AS cited_title,
       c.total_mentions AS total_mentions,
       c.ref_nums AS ref_nums,
       c.purpose_labels AS purpose_labels
LIMIT $limit
"""
        with self._driver.session() as session:
            rows = session.run(cypher, paper_sources=paper_sources, limit=limit)
            return [dict(r) for r in rows]

    def get_structured_knowledge_for_papers(
        self, paper_sources: list[str], *, max_claims: int = 30, max_steps: int = 20,
    ) -> dict[str, list[dict]]:
        """Fetch validated claims and logic steps for papers (used by RAG).

        Returns:
            {"claims": [...], "logic_steps": [...]}
        """
        if not paper_sources:
            return {"claims": [], "logic_steps": []}

        claims_cypher = """
MATCH (p:Paper)-[:HAS_CLAIM]->(cl:Claim)
WHERE p.paper_source IN $paper_sources
  AND coalesce(trim(toString(cl.claim_id)), '') <> ''
RETURN cl.claim_id AS claim_id,
       cl.text AS text,
       cl.step_type AS step_type,
       cl.kinds AS kinds,
       cl.confidence AS confidence,
       cl.evidence_quote AS evidence_quote,
       p.paper_source AS paper_source
ORDER BY coalesce(cl.confidence, -1.0) DESC,
         p.paper_source ASC,
         cl.claim_id ASC
LIMIT $limit
"""
        steps_cypher = """
MATCH (p:Paper)-[:HAS_LOGIC_STEP]->(s:LogicStep)
WHERE p.paper_source IN $paper_sources
RETURN s.step_type AS step_type,
       s.summary AS summary,
       s.confidence AS confidence,
       s.order AS step_order,
       p.paper_source AS paper_source
ORDER BY coalesce(s.order, 999) ASC,
         p.paper_source ASC,
         s.step_type ASC
LIMIT $limit
"""
        with self._driver.session() as session:
            claims = [dict(r) for r in session.run(claims_cypher, paper_sources=paper_sources, limit=max_claims)]
            steps = [dict(r) for r in session.run(steps_cypher, paper_sources=paper_sources, limit=max_steps)]
        return {"claims": claims, "logic_steps": steps}

    def list_papers(self, limit: int = 50, collection_id: str | None = None) -> list[dict]:
        cid = (collection_id or "").strip()
        if cid:
            if cid == "__uncategorized__":
                cypher = """
MATCH (p:Paper)
WHERE coalesce(p.ingested, false) = true
  AND NOT ( (:Collection)-[:HAS_PAPER]->(p) )
OPTIONAL MATCH (co:Collection)-[:HAS_PAPER]->(p)
WITH p, collect(co) AS cos
RETURN p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.doi AS doi,
       p.year AS year,
       [x IN cos WHERE x IS NOT NULL | {collection_id: x.collection_id, name: x.name}] AS collections
ORDER BY p.year DESC
LIMIT $limit
"""
                params = {"limit": limit}
            else:
                cypher = """
MATCH (co:Collection {collection_id:$collection_id})-[:HAS_PAPER]->(p:Paper)
WHERE coalesce(p.ingested, false) = true
OPTIONAL MATCH (co2:Collection)-[:HAS_PAPER]->(p)
WITH p, collect(co2) AS cos
RETURN p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.doi AS doi,
       p.year AS year,
       [x IN cos WHERE x IS NOT NULL | {collection_id: x.collection_id, name: x.name}] AS collections
ORDER BY p.year DESC
LIMIT $limit
"""
                params = {"limit": limit, "collection_id": cid}
        else:
            cypher = """
MATCH (p:Paper)
WHERE coalesce(p.ingested, false) = true
OPTIONAL MATCH (co:Collection)-[:HAS_PAPER]->(p)
WITH p, collect(co) AS cos
RETURN p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.doi AS doi,
       p.year AS year,
       [x IN cos WHERE x IS NOT NULL | {collection_id: x.collection_id, name: x.name}] AS collections
ORDER BY p.year DESC
LIMIT $limit
"""
            params = {"limit": limit}

        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, **params)]

    def list_papers_for_management(self, limit: int = 200, query: str | None = None) -> list[dict]:
        cypher = """
MATCH (p:Paper)
WHERE $search = ''
   OR toLower(coalesce(p.title, '')) CONTAINS $search
   OR toLower(coalesce(p.paper_source, '')) CONTAINS $search
   OR toLower(coalesce(p.doi, '')) CONTAINS $search
   OR toLower(coalesce(p.paper_id, '')) CONTAINS $search
OPTIONAL MATCH (co:Collection)-[:HAS_PAPER]->(p)
WITH p, collect(DISTINCT co) AS cos
RETURN p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.doi AS doi,
       p.year AS year,
       coalesce(p.ingested, false) AS ingested,
       CASE
         WHEN trim(coalesce(p.title, '')) <> '' THEN p.title
         WHEN trim(coalesce(p.paper_source, '')) <> '' THEN p.paper_source
         ELSE p.paper_id
       END AS display_title,
       coalesce(p.ingested, false) AS deletable,
       [x IN cos WHERE x IS NOT NULL | {collection_id: x.collection_id, name: x.name}] AS collections
ORDER BY coalesce(p.ingested, false) DESC,
         coalesce(p.year, 0) DESC,
         toLower(
           CASE
             WHEN trim(coalesce(p.title, '')) <> '' THEN p.title
             WHEN trim(coalesce(p.paper_source, '')) <> '' THEN p.paper_source
             ELSE p.paper_id
           END
         ) ASC
LIMIT $limit
"""
        params = {
            "limit": int(limit),
            "search": str(query or "").strip().lower(),
        }
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, **params)]

    def list_collections(self, limit: int = 200) -> list[dict]:
        cypher = """
MATCH (co:Collection)
RETURN co.collection_id AS collection_id,
       co.name AS name,
       co.created_at AS created_at,
       co.updated_at AS updated_at
ORDER BY coalesce(co.updated_at, co.created_at) DESC, co.name ASC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, limit=limit)]

    def list_paper_sources_for_collection(self, collection_id: str) -> list[str]:
        cid = (collection_id or "").strip()
        if not cid:
            return []
        cypher = """
MATCH (co:Collection {collection_id:$collection_id})-[:HAS_PAPER]->(p:Paper)
RETURN DISTINCT p.paper_source AS paper_source
"""
        with self._driver.session() as session:
            rows = session.run(cypher, collection_id=cid)
            out: list[str] = []
            for r in rows:
                ps = str(r.get("paper_source") or "").strip()
                if ps:
                    out.append(ps)
            return out

    def list_paper_sources_for_paper_ids(self, paper_ids: list[str]) -> list[str]:
        ids = [str(x).strip() for x in (paper_ids or []) if str(x).strip()]
        if not ids:
            return []
        cypher = """
MATCH (p:Paper)
WHERE p.paper_id IN $paper_ids OR p.paper_source IN $paper_ids
RETURN DISTINCT p.paper_source AS paper_source
"""
        with self._driver.session() as session:
            rows = session.run(cypher, paper_ids=ids)
            out: list[str] = []
            for r in rows:
                ps = str(r.get("paper_source") or "").strip()
                if ps:
                    out.append(ps)
            return out

    def list_papers_by_ids(self, paper_ids: list[str], limit: int = 5000) -> list[dict]:
        ids = [str(x).strip() for x in (paper_ids or []) if str(x).strip()]
        if not ids:
            return []
        limit = max(1, min(5000, int(limit)))
        cypher = """
MATCH (p:Paper)
WHERE p.paper_id IN $paper_ids
RETURN p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.year AS year,
       p.doi AS doi
ORDER BY coalesce(p.year, 0) DESC, p.paper_id ASC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, paper_ids=ids, limit=limit)]

    def list_paper_ids_for_claims(self, claim_ids: list[str], limit: int = 200) -> list[str]:
        ids = [str(x).strip() for x in (claim_ids or []) if str(x).strip()]
        if not ids:
            return []
        limit = max(1, min(5000, int(limit)))
        cypher = """
MATCH (p:Paper)-[:HAS_CLAIM]->(cl:Claim)
WHERE cl.claim_id IN $claim_ids
RETURN DISTINCT p.paper_id AS paper_id
LIMIT $limit
"""
        with self._driver.session() as session:
            rows = session.run(cypher, claim_ids=ids, limit=limit)
            return [str(r.get("paper_id") or "").strip() for r in rows if str(r.get("paper_id") or "").strip()]

    def _sample_author_hop_papers(
        self,
        *,
        target_ids: list[str],
        hop: int,
        limit: int,
    ) -> list[dict]:
        if not target_ids or limit <= 0:
            return []
        with self._driver.session() as session:
            cypher_adj = f"""
MATCH (tp:Paper)
WHERE tp.paper_id IN $target_ids
MATCH (tp)<-[:AUTHORED]-(a0:Author)-[:CO_AUTHOR*1..{hop}]-(an:Author)-[:AUTHORED]->(p:Paper)
WHERE coalesce(p.ingested, false) = true
  AND NOT p.paper_id IN $target_ids
RETURN DISTINCT p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.year AS year
ORDER BY coalesce(p.year, 0) DESC, p.paper_id ASC
LIMIT $limit
"""
            return [dict(r) for r in session.run(cypher_adj, target_ids=target_ids, limit=limit)]

    def _local_paper_graph_for_louvain(
        self,
        *,
        target_ids: list[str],
        max_nodes: int = 260,
        max_edges: int = 2400,
    ) -> tuple[dict[str, dict], list[tuple[str, str, float]]]:
        if not target_ids:
            return {}, []
        node_rows: list[dict] = []
        with self._driver.session() as session:
            node_rows = [
                dict(r)
                for r in session.run(
                    """
MATCH (tp:Paper)
WHERE tp.paper_id IN $target_ids
OPTIONAL MATCH (tp)-[:CITES*1..2]-(np:Paper)
WHERE coalesce(np.ingested, false) = true
WITH collect(DISTINCT tp) + collect(DISTINCT np) AS papers
UNWIND papers AS p
WITH DISTINCT p
WHERE coalesce(p.ingested, false) = true
RETURN p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.year AS year
LIMIT $limit
""",
                    target_ids=target_ids,
                    limit=max(20, min(1200, int(max_nodes))),
                )
            ]
            if not node_rows:
                node_rows = [
                    dict(r)
                    for r in session.run(
                        """
MATCH (p:Paper)
WHERE p.paper_id IN $target_ids
RETURN p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.year AS year
""",
                        target_ids=target_ids,
                    )
                ]

            node_ids = [str(r.get("paper_id") or "").strip() for r in node_rows if str(r.get("paper_id") or "").strip()]
            if len(node_ids) < 2:
                return {nid: r for nid, r in zip(node_ids, node_rows)}, []

            cite_rows = [
                dict(r)
                for r in session.run(
                    """
UNWIND $node_ids AS pid
MATCH (a:Paper {paper_id: pid})-[c:CITES]-(b:Paper)
WHERE b.paper_id IN $node_ids AND a.paper_id < b.paper_id
RETURN a.paper_id AS src, b.paper_id AS dst, count(c) AS weight
LIMIT $max_edges
""",
                    node_ids=node_ids,
                    max_edges=max(200, min(8000, int(max_edges))),
                )
            ]
            coauthor_rows = [
                dict(r)
                for r in session.run(
                    """
UNWIND $node_ids AS pid
MATCH (a:Paper {paper_id: pid})<-[:AUTHORED]-(au:Author)-[:AUTHORED]->(b:Paper)
WHERE b.paper_id IN $node_ids AND a.paper_id < b.paper_id
RETURN a.paper_id AS src, b.paper_id AS dst, count(DISTINCT au) AS weight
LIMIT $max_edges
""",
                    node_ids=node_ids,
                    max_edges=max(200, min(8000, int(max_edges))),
                )
            ]

        node_map: dict[str, dict] = {}
        for row in node_rows:
            pid = str(row.get("paper_id") or "").strip()
            if not pid:
                continue
            node_map[pid] = {
                "paper_id": pid,
                "paper_source": str(row.get("paper_source") or ""),
                "title": str(row.get("title") or ""),
                "year": row.get("year"),
            }

        edge_weight: dict[tuple[str, str], float] = {}
        for row in cite_rows:
            a = str(row.get("src") or "").strip()
            b = str(row.get("dst") or "").strip()
            if not a or not b or a == b:
                continue
            key = (a, b) if a < b else (b, a)
            edge_weight[key] = edge_weight.get(key, 0.0) + max(0.0, float(row.get("weight") or 0.0))
        for row in coauthor_rows:
            a = str(row.get("src") or "").strip()
            b = str(row.get("dst") or "").strip()
            if not a or not b or a == b:
                continue
            key = (a, b) if a < b else (b, a)
            edge_weight[key] = edge_weight.get(key, 0.0) + 0.6 * max(0.0, float(row.get("weight") or 0.0))

        edges = [(a, b, w) for (a, b), w in edge_weight.items() if w > 0.0]
        return node_map, edges

    def _sample_louvain_community_papers(
        self,
        *,
        target_ids: list[str],
        limit: int,
    ) -> list[dict]:
        if not target_ids or limit <= 0:
            return []
        node_map, edges = self._local_paper_graph_for_louvain(target_ids=target_ids)
        if not node_map:
            return []
        partition = _local_louvain_partition(list(node_map.keys()), edges)
        if not partition:
            return []
        target_comms = {partition.get(tid) for tid in target_ids if tid in partition}
        target_comms = {c for c in target_comms if c is not None}
        if not target_comms:
            return []
        rows = [
            node_map[pid]
            for pid, comm in partition.items()
            if comm in target_comms and pid not in target_ids and pid in node_map
        ]
        rows.sort(
            key=lambda r: (
                int(r.get("year") or 0),
                str(r.get("paper_id") or ""),
            ),
            reverse=True,
        )
        return rows[: max(0, int(limit))]

    def sample_inspiration_papers(
        self,
        *,
        target_paper_ids: list[str],
        hop_order: int = 2,
        adjacent_samples: int = 6,
        random_samples: int = 2,
        community_method: str = "author_hop",
        community_samples: int = 4,
    ) -> dict:
        target_ids = [str(x).strip() for x in (target_paper_ids or []) if str(x).strip()]
        hop = max(1, min(3, int(hop_order)))
        adj_k = max(0, min(30, int(adjacent_samples)))
        rand_k = max(0, min(30, int(random_samples)))
        comm_k = max(0, min(30, int(community_samples)))
        method = str(community_method or "author_hop").strip().lower()
        if method not in {"author_hop", "louvain", "hybrid"}:
            method = "author_hop"

        if not target_ids:
            return {"adjacent_papers": [], "community_papers": [], "random_papers": [], "community_method": method}

        adjacent: list[dict] = self._sample_author_hop_papers(target_ids=target_ids, hop=hop, limit=adj_k) if method in {"author_hop", "hybrid"} else []
        community_rows: list[dict] = self._sample_louvain_community_papers(target_ids=target_ids, limit=comm_k) if method in {"louvain", "hybrid"} else []

        if method == "louvain":
            adjacent = [dict(r) for r in community_rows[:adj_k]]
        elif method == "hybrid" and adj_k > 0:
            merged: list[dict] = []
            seen_ids: set[str] = set()
            for row in [*adjacent, *community_rows]:
                pid = str(row.get("paper_id") or "").strip()
                if not pid or pid in seen_ids or pid in target_ids:
                    continue
                seen_ids.add(pid)
                merged.append(dict(row))
                if len(merged) >= adj_k:
                    break
            adjacent = merged

        excluded_ids = list(
            {
                *target_ids,
                *[str(r.get("paper_id") or "").strip() for r in adjacent],
                *[str(r.get("paper_id") or "").strip() for r in community_rows],
            }
        )
        random_rows: list[dict] = []
        if rand_k > 0:
            with self._driver.session() as session:
                cypher_rand = """
MATCH (p:Paper)
WHERE coalesce(p.ingested, false) = true
  AND NOT p.paper_id IN $excluded_ids
RETURN p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.year AS year
ORDER BY rand()
LIMIT $limit
"""
                random_rows = [dict(r) for r in session.run(cypher_rand, excluded_ids=excluded_ids, limit=rand_k)]

        return {
            "adjacent_papers": adjacent,
            "community_papers": community_rows[:comm_k] if comm_k > 0 else [],
            "random_papers": random_rows,
            "community_method": method,
        }

    def create_collection(self, collection_id: str, name: str, created_at: str) -> None:
        cypher = """
CREATE (co:Collection {collection_id:$collection_id})
SET co.name = $name,
    co.created_at = $created_at,
    co.updated_at = $created_at
"""
        with self._driver.session() as session:
            session.run(cypher, collection_id=collection_id, name=name, created_at=created_at)

    def rename_collection(self, collection_id: str, name: str, updated_at: str) -> None:
        cypher = """
MATCH (co:Collection {collection_id:$collection_id})
SET co.name = $name,
    co.updated_at = $updated_at
"""
        with self._driver.session() as session:
            session.run(cypher, collection_id=collection_id, name=name, updated_at=updated_at)

    def delete_collection(self, collection_id: str) -> None:
        cypher = """
MATCH (co:Collection {collection_id:$collection_id})
DETACH DELETE co
"""
        with self._driver.session() as session:
            session.run(cypher, collection_id=collection_id)

    def add_paper_to_collection(self, collection_id: str, paper_id: str) -> None:
        cypher = """
MATCH (co:Collection {collection_id:$collection_id})
MATCH (p:Paper {paper_id:$paper_id})
MERGE (co)-[:HAS_PAPER]->(p)
"""
        with self._driver.session() as session:
            session.run(cypher, collection_id=collection_id, paper_id=paper_id)

    def remove_paper_from_collection(self, collection_id: str, paper_id: str) -> None:
        cypher = """
MATCH (co:Collection {collection_id:$collection_id})-[r:HAS_PAPER]->(p:Paper {paper_id:$paper_id})
DELETE r
"""
        with self._driver.session() as session:
            session.run(cypher, collection_id=collection_id, paper_id=paper_id)

    def remove_paper_from_all_collections(self, paper_id: str) -> None:
        cypher = """
MATCH (:Collection)-[r:HAS_PAPER]->(p:Paper {paper_id:$paper_id})
DELETE r
"""
        with self._driver.session() as session:
            session.run(cypher, paper_id=paper_id)

    def get_paper_detail(self, paper_id: str) -> dict:
        with self._driver.session() as session:
            p_row = session.run(
                """
MATCH (p:Paper {paper_id:$paper_id})
RETURN p
""",
                paper_id=paper_id,
            ).single()
            if not p_row:
                # Fallback: try matching by paper_source (e.g. "13_2334")
                p_row = session.run(
                    """
MATCH (p:Paper {paper_source:$paper_source})
RETURN p
""",
                    paper_source=paper_id,
                ).single()
            if not p_row:
                raise KeyError(f"Paper not found: {paper_id}")
            paper = dict(p_row["p"])

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

            human_meta = _safe_json(paper.get("human_meta_json"), {})
            meta_cleared = set(_safe_json(paper.get("human_meta_cleared_json"), []))
            human_logic = _safe_json(paper.get("human_logic_json"), {})
            logic_cleared = set(_safe_json(paper.get("human_logic_cleared_json"), []))
            human_claims = _safe_json(paper.get("human_claims_json"), {})
            claims_cleared = set(_safe_json(paper.get("human_claims_cleared_json"), []))
            human_cites = _safe_json(paper.get("human_cites_purpose_json"), {})
            cites_cleared = set(_safe_json(paper.get("human_cites_purpose_cleared_json"), []))
            paper["phase1_quality"] = _safe_json(paper.get("phase1_quality_json"), {})
            paper["phase1_gate_passed"] = bool(paper.get("phase1_gate_passed"))
            paper["phase1_quality_tier"] = str(paper.get("phase1_quality_tier") or "")
            try:
                paper["phase1_quality_tier_score"] = float(paper.get("phase1_quality_tier_score") or 0.0)
            except Exception:
                paper["phase1_quality_tier_score"] = 0.0

            pending_task_id = paper.get("review_pending_task_id")
            resolved_task_id = paper.get("review_resolved_task_id")
            has_human_edits = bool(
                human_meta
                or meta_cleared
                or human_logic
                or logic_cleared
                or human_claims
                or claims_cleared
                or human_cites
                or cites_cleared
            )
            needs_review = bool(pending_task_id and pending_task_id != resolved_task_id and has_human_edits)

            # Apply editable metadata overlays (effective values exposed via paper.title/year, but keep machine copy).
            paper["title_machine"] = paper.get("title")
            paper["year_machine"] = paper.get("year")
            if "title" in meta_cleared:
                paper["title"] = ""
                paper["title_source"] = "cleared"
            elif isinstance(human_meta, dict) and human_meta.get("title") is not None:
                paper["title"] = str(human_meta.get("title") or "")
                paper["title_source"] = "human"
            else:
                paper["title_source"] = "machine"

            if "year" in meta_cleared:
                paper["year"] = None
                paper["year_source"] = "cleared"
            elif isinstance(human_meta, dict) and human_meta.get("year") is not None:
                try:
                    paper["year"] = int(human_meta.get("year"))
                except Exception:
                    paper["year"] = None
                paper["year_source"] = "human"
            else:
                paper["year_source"] = "machine"

            stats = session.run(
                """
MATCH (p:Paper {paper_id:$paper_id})
OPTIONAL MATCH (p)-[:HAS_CHUNK]->(c:Chunk)
OPTIONAL MATCH (p)-[:HAS_REFERENCE]->(r:ReferenceEntry)
RETURN count(DISTINCT c) AS chunk_count, count(DISTINCT r) AS ref_count
""",
                paper_id=paper_id,
            ).single()

            logic_steps_raw = [
                dict(r)
                for r in session.run(
                    """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_LOGIC_STEP]->(s:LogicStep)
RETURN s.step_type AS step_type, s.summary AS summary, s.confidence AS confidence, s.order AS order
ORDER BY coalesce(s.order, 999) ASC, s.step_type ASC
""",
                    paper_id=paper_id,
                )
            ]

            # Overlay logic step edits
            logic_steps: list[dict] = []
            for s in logic_steps_raw:
                st = str(s.get("step_type") or "")
                machine_summary = s.get("summary")
                machine_conf = s.get("confidence")
                human_summary = human_logic.get(st) if isinstance(human_logic, dict) else None
                cleared = st in logic_cleared
                if cleared:
                    effective = ""
                    source = "cleared"
                elif human_summary is not None:
                    effective = str(human_summary)
                    source = "human"
                else:
                    effective = machine_summary
                    source = "machine"
                out = dict(s)
                out["summary_machine"] = machine_summary
                out["confidence_machine"] = machine_conf
                out["summary_human"] = None if human_summary is None else str(human_summary)
                out["source"] = source
                out["summary"] = effective
                if needs_review and source in {"human", "cleared"}:
                    out["pending_machine_summary"] = machine_summary
                    out["pending_machine_confidence"] = machine_conf
                logic_steps.append(out)

            claims_raw = [
                dict(r)
                for r in session.run(
                    """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_CLAIM]->(cl:Claim)
RETURN cl.claim_id AS claim_id,
       cl.claim_key AS claim_key,
       cl.text AS text,
       cl.confidence AS confidence,
       cl.step_type AS step_type,
       cl.kinds AS kinds,
       cl.evidence_weak AS evidence_weak,
       cl.targets_paper_ids AS targets_paper_ids
ORDER BY cl.confidence DESC, cl.claim_key ASC
LIMIT 400
""",
                    paper_id=paper_id,
                )
            ]

            def _norm_claim_text(t: str) -> str:
                s = " ".join((t or "").split()).strip()
                while s and s[-1] in ".;銆傦紱":
                    s = s[:-1].rstrip()
                return s

            def _claim_key_for(text: str) -> str:
                doi = str(paper.get("doi") or "")
                base = (doi.strip().lower() + "\0" + _norm_claim_text(text)).encode("utf-8", errors="ignore")
                return hashlib.sha256(base).hexdigest()[:24]

            # Overlay claim edits (and include human-only claims)
            machine_keys: set[str] = set()
            claims: list[dict] = []
            for c in claims_raw:
                key = str(c.get("claim_key") or "") or _claim_key_for(str(c.get("text") or ""))
                machine_keys.add(key)
                machine_text = c.get("text")
                human_text = human_claims.get(key) if isinstance(human_claims, dict) else None
                cleared = key in claims_cleared
                if cleared:
                    effective = ""
                    source = "cleared"
                elif human_text is not None:
                    effective = str(human_text)
                    source = "human"
                else:
                    effective = machine_text
                    source = "machine"
                out = dict(c)
                out["claim_key"] = key
                out["text_machine"] = machine_text
                out["confidence_machine"] = out.get("confidence")
                out["text_human"] = None if human_text is None else str(human_text)
                out["source"] = source
                out["text"] = effective
                if needs_review and source in {"human", "cleared"}:
                    out["pending_machine_text"] = machine_text
                    out["pending_machine_confidence"] = out.get("confidence")
                claims.append(out)

            # Attach evidence for logic steps (LogicStep -> Chunk).
            try:
                step_evidence_rows = [
                    dict(r)
                    for r in session.run(
                        """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_LOGIC_STEP]->(ls:LogicStep)-[e:EVIDENCED_BY]->(ch:Chunk)
RETURN ls.step_type AS step_type,
       ch.chunk_id AS chunk_id,
       ch.section AS section,
       ch.start_line AS start_line,
       ch.end_line AS end_line,
       ch.kind AS kind,
       ch.text AS text,
       e.source AS source,
       e.weak AS weak
""",
                        paper_id=paper_id,
                    )
                ]
                step_by_machine: dict[str, list[dict]] = {}
                step_by_human: dict[str, list[dict]] = {}
                for r in step_evidence_rows:
                    st = str(r.get("step_type") or "")
                    if not st:
                        continue
                    src = str(r.get("source") or "machine").strip().lower()
                    txt = str(r.get("text") or "").strip().replace("\n", " ")
                    txt = " ".join(txt.split())[:600]
                    out = {
                        "chunk_id": r.get("chunk_id"),
                        "section": r.get("section"),
                        "start_line": r.get("start_line"),
                        "end_line": r.get("end_line"),
                        "kind": r.get("kind"),
                        "snippet": txt,
                        "weak": bool(r.get("weak") or False),
                        "source": src,
                    }
                    if src == "human":
                        step_by_human.setdefault(st, []).append(out)
                    else:
                        step_by_machine.setdefault(st, []).append(out)
                for m in (step_by_machine, step_by_human):
                    for st in list(m.keys()):
                        m[st].sort(key=lambda x: (int(x.get("start_line") or 0), str(x.get("chunk_id") or "")))

                for s in logic_steps:
                    st = str(s.get("step_type") or "")
                    if not st:
                        continue
                    s["evidence_machine"] = step_by_machine.get(st, [])
                    s["evidence_human"] = step_by_human.get(st, [])
                    s["evidence"] = s["evidence_human"] or s["evidence_machine"]
            except Exception:
                pass

            # add human-only claims (including cleared placeholders)
            if isinstance(human_claims, dict):
                for key, txt in human_claims.items():
                    k = str(key)
                    if k in machine_keys:
                        continue
                    cleared = k in claims_cleared
                    out = {
                        "claim_id": None,
                        "claim_key": k,
                        "confidence": None,
                        "confidence_machine": None,
                        "text_machine": None,
                        "text_human": None if txt is None else str(txt),
                        "source": "cleared" if cleared else "human",
                        "text": "" if cleared else (None if txt is None else str(txt)),
                    }
                    if needs_review and out["source"] in {"human", "cleared"}:
                        out["pending_machine_text"] = None
                        out["pending_machine_confidence"] = None
                    claims.append(out)
            for k in sorted(claims_cleared):
                if k in machine_keys:
                    continue
                if isinstance(human_claims, dict) and k in human_claims:
                    continue
                out = {
                    "claim_id": None,
                    "claim_key": k,
                    "confidence": None,
                    "confidence_machine": None,
                    "text_machine": None,
                    "text_human": None,
                    "source": "cleared",
                    "text": "",
                }
                if needs_review:
                    out["pending_machine_text"] = None
                    out["pending_machine_confidence"] = None
                claims.append(out)

            # Attach evidence (Claim -> Chunk) and targets (Claim -> Paper) for machine claims.
            try:
                evidence_rows = [
                    dict(r)
                    for r in session.run(
                        """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_CLAIM]->(cl:Claim)-[e:EVIDENCED_BY]->(ch:Chunk)
RETURN cl.claim_key AS claim_key,
       ch.chunk_id AS chunk_id,
       ch.section AS section,
       ch.start_line AS start_line,
       ch.end_line AS end_line,
       ch.kind AS kind,
       ch.text AS text,
       e.source AS source,
       e.weak AS weak
""",
                        paper_id=paper_id,
                    )
                ]
                by_key_machine: dict[str, list[dict]] = {}
                by_key_human: dict[str, list[dict]] = {}
                for r in evidence_rows:
                    k = str(r.get("claim_key") or "")
                    if not k:
                        continue
                    src = str(r.get("source") or "machine").strip().lower()
                    txt = str(r.get("text") or "").strip().replace("\n", " ")
                    txt = " ".join(txt.split())[:600]
                    out = {
                        "chunk_id": r.get("chunk_id"),
                        "section": r.get("section"),
                        "start_line": r.get("start_line"),
                        "end_line": r.get("end_line"),
                        "kind": r.get("kind"),
                        "snippet": txt,
                        "weak": bool(r.get("weak") or False),
                        "source": src,
                    }
                    if src == "human":
                        by_key_human.setdefault(k, []).append(out)
                    else:
                        by_key_machine.setdefault(k, []).append(out)

                # stable ordering: human first by line, machine by line
                for m in (by_key_machine, by_key_human):
                    for kk in list(m.keys()):
                        m[kk].sort(key=lambda x: (int(x.get("start_line") or 0), str(x.get("chunk_id") or "")))

                target_rows = [
                    dict(r)
                    for r in session.run(
                        """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_CLAIM]->(cl:Claim)-[:TARGETS_PAPER]->(tp:Paper)
RETURN cl.claim_key AS claim_key,
       tp.paper_id AS paper_id,
       tp.doi AS doi,
       tp.title AS title,
       tp.year AS year
""",
                        paper_id=paper_id,
                    )
                ]
                targets_by_key: dict[str, list[dict]] = {}
                for r in target_rows:
                    k = str(r.get("claim_key") or "")
                    if not k:
                        continue
                    targets_by_key.setdefault(k, []).append(
                        {
                            "paper_id": r.get("paper_id"),
                            "doi": r.get("doi"),
                            "title": r.get("title"),
                            "year": r.get("year"),
                        }
                    )

                for c in claims:
                    k = str(c.get("claim_key") or "")
                    if not k:
                        continue
                    c["evidence_machine"] = by_key_machine.get(k, [])
                    c["evidence_human"] = by_key_human.get(k, [])
                    c["evidence"] = c["evidence_human"] if c["evidence_human"] else c["evidence_machine"]
                    c["targets"] = targets_by_key.get(k, [])
            except Exception:
                pass

            outgoing_raw = [
                dict(r)
                for r in session.run(
                    """
MATCH (p:Paper {paper_id:$paper_id})-[c:CITES]->(q:Paper)
RETURN q.paper_id AS cited_paper_id,
       q.doi AS cited_doi,
       q.title AS cited_title,
       c.total_mentions AS total_mentions,
       c.ref_nums AS ref_nums,
       c.evidence_chunk_ids AS evidence_chunk_ids,
       c.evidence_spans AS evidence_spans,
       c.purpose_labels AS purpose_labels,
       c.purpose_scores AS purpose_scores
ORDER BY c.total_mentions DESC
LIMIT 200
""",
                    paper_id=paper_id,
                )
            ]

            citation_acts, citation_mentions = _load_citation_enrichment_artifacts(paper_id)
            outgoing = _merge_outgoing_citation_enrichment(
                outgoing_raw=outgoing_raw,
                human_cites=human_cites,
                cites_cleared=cites_cleared,
                needs_review=needs_review,
                citation_acts=citation_acts,
                citation_mentions=citation_mentions,
            )

            unresolved = [
                dict(r)
                for r in session.run(
                    """
MATCH (p:Paper {paper_id:$paper_id})-[u:CITES_UNRESOLVED]->(re:ReferenceEntry)
RETURN re.ref_id AS ref_id,
       re.raw AS raw,
       re.crossref_json AS crossref_json,
       u.total_mentions AS total_mentions,
       u.ref_nums AS ref_nums
ORDER BY u.total_mentions DESC
LIMIT 200
""",
                    paper_id=paper_id,
                )
            ]

            figures = [
                dict(r)
                for r in session.run(
                    """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_FIGURE]->(f:Figure)
RETURN f.figure_id AS figure_id,
       f.rel_path AS rel_path,
       f.filename AS filename,
       f.img_line AS img_line,
       f.caption_text AS caption_text,
       f.caption_start_line AS caption_start_line,
       f.caption_end_line AS caption_end_line
ORDER BY f.img_line ASC
LIMIT 500
""",
                    paper_id=paper_id,
                )
            ]

            # Review summary (count only human/cleared items).
            pending_count = 0
            if needs_review:
                if isinstance(human_meta, dict):
                    pending_count += len([k for k, v in human_meta.items() if v is not None])
                pending_count += len(meta_cleared)
                pending_count += len([x for x in logic_steps if x.get("source") in {"human", "cleared"}])
                pending_count += len([x for x in claims if x.get("source") in {"human", "cleared"}])
                pending_count += len([x for x in outgoing if x.get("purpose_source") in {"human", "cleared"}])

            paper["review_pending_task_id"] = pending_task_id
            paper["review_resolved_task_id"] = resolved_task_id
            paper["review_needs_review"] = needs_review
            paper["review_pending_count"] = pending_count

            schema = None
            try:
                from app.schema_store import load_version, normalize_paper_type

                pt = normalize_paper_type(paper.get("schema_paper_type") or paper.get("paper_type"))
                v = int(paper.get("schema_version") or 1)
                schema = load_version(pt, v)  # type: ignore[arg-type]
            except Exception:
                schema = None

            return {
                "paper": paper,
                "schema": schema,
                "stats": dict(stats) if stats else {},
                "logic_steps": logic_steps,
                "claims": claims,
                "outgoing_cites": outgoing,
                "unresolved": unresolved,
                "figures": figures,
            }

    def update_paper_props(self, paper_id: str, props: dict) -> None:
        cypher = """
MATCH (p:Paper {paper_id:$paper_id})
SET p += $props
"""
        with self._driver.session() as session:
            session.run(cypher, paper_id=paper_id, props=props)

    @staticmethod
    def _claim_id_for(paper_id: str, claim_key: str) -> str:
        base = (str(paper_id) + "\0" + str(claim_key)).encode("utf-8", errors="ignore")
        return hashlib.sha256(base).hexdigest()[:24]

    def upsert_human_only_claim_node(self, paper_id: str, claim_key: str, text: str) -> str:
        """
        Ensure a Claim node exists for a human-only claim (created via UI).

        Safety:
        - If a machine Claim with the same claim_id already exists, we do NOT overwrite its text.
        - We only update cl.text when cl.source == 'human'.
        """
        pid = str(paper_id or "").strip()
        ck = str(claim_key or "").strip()
        txt = str(text or "").strip()
        if not pid or not ck:
            raise ValueError("paper_id/claim_key required")
        claim_id = self._claim_id_for(pid, ck)
        cypher = """
MATCH (p:Paper {paper_id:$paper_id})
MERGE (cl:Claim {claim_id:$claim_id})
ON CREATE SET cl.paper_id = $paper_id,
              cl.claim_key = $claim_key,
              cl.text = $text,
              cl.confidence = null,
              cl.step_type = null,
              cl.kinds = [],
              cl.evidence_weak = false,
              cl.targets_paper_ids = [],
              cl.source = 'human'
MERGE (p)-[:HAS_CLAIM]->(cl)
SET cl.claim_key = coalesce(cl.claim_key, $claim_key)
WITH cl
SET cl.text = CASE WHEN coalesce(cl.source,'') = 'human' THEN $text ELSE cl.text END
"""
        with self._driver.session() as session:
            session.run(cypher, paper_id=pid, claim_id=claim_id, claim_key=ck, text=txt)
        return claim_id

    def get_paper_basic(self, paper_id: str) -> dict:
        with self._driver.session() as session:
            row = session.run(
                """
MATCH (p:Paper {paper_id:$paper_id})
RETURN p
""",
                paper_id=paper_id,
            ).single()
            if not row:
                raise KeyError(f"Paper not found: {paper_id}")
            return dict(row["p"])

    def delete_paper_subgraph(self, paper_id: str) -> None:
        """
        Delete all nodes/edges that belong to the given paper, but keep the Paper node itself
        so that incoming CITES edges from other papers remain valid.
        """
        stmts = [
            # Outgoing relationships
            """
MATCH (p:Paper {paper_id:$paper_id})-[c:CITES]->()
DELETE c
""",
            """
MATCH (p:Paper {paper_id:$paper_id})-[u:CITES_UNRESOLVED]->()
DELETE u
""",
            # Delete EvidenceEvents belonging to this paper's claims (before deleting claims)
            """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_CLAIM]->(cl:Claim)-[:TRIGGERS_EVENT]->(ev:EvidenceEvent)
DETACH DELETE ev
""",
            # Owned sub-nodes
            """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_CHUNK]->(c:Chunk)
DETACH DELETE c
""",
            """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_LOGIC_STEP]->(s:LogicStep)
DETACH DELETE s
""",
            """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_CLAIM]->(cl:Claim)
DETACH DELETE cl
""",
            """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_REFERENCE]->(re:ReferenceEntry)
DETACH DELETE re
""",
            # Future-proof: if figures exist, remove them as well.
            """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_FIGURE]->(f:Figure)
DETACH DELETE f
""",
        ]
        with self._driver.session() as session:
            for s in stmts:
                session.run(s, paper_id=paper_id)

    def delete_paper_node(self, paper_id: str) -> None:
        """
        Hard delete the Paper node itself (and any remaining incident relationships).
        Intended for user-facing full deletion scenarios.
        """
        with self._driver.session() as session:
            session.run(
                """
MATCH (p:Paper {paper_id:$paper_id})
DETACH DELETE p
""",
                paper_id=paper_id,
            )

    def list_chunks_for_faiss(self, limit: int = 200000) -> list[dict]:
        cypher = """
MATCH (p:Paper)-[:HAS_CHUNK]->(c:Chunk)
WHERE coalesce(p.ingested, false) = true AND coalesce(c.kind,'') <> 'heading'
RETURN c.chunk_id AS chunk_id,
       c.paper_source AS paper_source,
       c.md_path AS md_path,
       c.start_line AS start_line,
       c.end_line AS end_line,
       c.section AS section,
       c.kind AS kind,
       c.text AS text
ORDER BY c.chunk_id
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, limit=limit)]

    def list_chunks_for_paper(self, paper_id: str, limit: int = 8000) -> list[dict]:
        cypher = """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_CHUNK]->(c:Chunk)
RETURN c.chunk_id AS chunk_id,
       c.section AS section,
       c.kind AS kind,
       c.start_line AS start_line,
       c.end_line AS end_line,
       c.text AS text
ORDER BY c.start_line ASC, c.chunk_id ASC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, paper_id=paper_id, limit=limit)]

    def set_claim_evidence(self, paper_id: str, claim_key: str, chunk_ids: list[str], source: str = "human") -> None:
        src = (source or "human").strip().lower()
        if src not in {"human", "machine"}:
            src = "human"
        cypher = """
MATCH (p:Paper {paper_id:$paper_id})-[:HAS_CLAIM]->(cl:Claim)
WHERE cl.claim_key = $claim_key
OPTIONAL MATCH (cl)-[e:EVIDENCED_BY]->(:Chunk)
WHERE coalesce(e.source,'machine') = $source
DELETE e
WITH cl
UNWIND $chunk_ids AS cid
MATCH (ch:Chunk {chunk_id: cid})
MERGE (cl)-[e:EVIDENCED_BY {source:$source}]->(ch)
SET e.weak = false
"""
        with self._driver.session() as session:
            session.run(cypher, paper_id=paper_id, claim_key=claim_key, chunk_ids=list(chunk_ids or []), source=src)

    def apply_human_claim_evidence_overrides(self, paper_id: str) -> None:
        """
        Re-apply Paper-level human evidence overrides after a rebuild/replace.
        Stores are on the Paper node so they survive; Claim/Chunk nodes are recreated.
        """
        paper = self.get_paper_basic(paper_id)

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

        evidence = _safe_json(paper.get("human_claim_evidence_json"), {})
        cleared = set(_safe_json(paper.get("human_claim_evidence_cleared_json"), []))
        if not isinstance(evidence, dict):
            evidence = {}

        for key, ids in evidence.items():
            ck = str(key)
            if not ck:
                continue
            chunk_ids = [str(x).strip() for x in (ids or []) if str(x).strip()]
            self.set_claim_evidence(paper_id, ck, chunk_ids, source="human")
        for ck in cleared:
            self.set_claim_evidence(paper_id, str(ck), [], source="human")

    def list_unresolved(self, limit: int = 100) -> list[dict]:
        cypher = """
MATCH (p:Paper)-[u:CITES_UNRESOLVED]->(re:ReferenceEntry)
WHERE coalesce(p.ingested, false) = true
RETURN p.paper_id AS citing_paper_id,
       p.paper_source AS citing_paper_source,
       re.ref_id AS ref_id,
       re.raw AS raw,
       re.crossref_json AS crossref_json,
       u.total_mentions AS total_mentions,
       u.ref_nums AS ref_nums
ORDER BY u.total_mentions DESC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, limit=limit)]

    def upsert_figures(self, paper_id: str, figures: list[dict]) -> None:
        if not figures:
            return
        cypher = """
MATCH (p:Paper {paper_id:$paper_id})
WITH p
UNWIND $figures AS f
MERGE (x:Figure {figure_id: f.figure_id})
SET x += f
MERGE (p)-[:HAS_FIGURE]->(x)
"""
        with self._driver.session() as session:
            session.run(cypher, paper_id=paper_id, figures=figures)

    def get_network(
        self,
        limit_papers: int = 200,
        limit_edges: int = 500,
        collection_id: str | None = None,
        paper_ids: list[str] | None = None,
    ) -> dict:
        with self._driver.session() as session:
            cid = (collection_id or "").strip()
            ids = [str(x).strip() for x in (paper_ids or []) if str(x).strip()]
            if ids:
                base_nodes = [
                    dict(r)
                    for r in session.run(
                        """
MATCH (p:Paper)
WHERE p.paper_id IN $paper_ids
RETURN p.paper_id AS id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.doi AS doi,
       p.year AS year,
       coalesce(p.ingested, false) AS ingested
ORDER BY p.year DESC
LIMIT $limit
""",
                        paper_ids=ids,
                        limit=limit_papers,
                    )
                ]
            elif cid:
                base_nodes = [
                    dict(r)
                    for r in session.run(
                        """
MATCH (co:Collection {collection_id:$collection_id})-[:HAS_PAPER]->(p:Paper)
RETURN p.paper_id AS id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.doi AS doi,
       p.year AS year,
       coalesce(p.ingested, false) AS ingested
ORDER BY p.year DESC
LIMIT $limit
""",
                        collection_id=cid,
                        limit=limit_papers,
                    )
                ]
            else:
                base_nodes = [
                    dict(r)
                    for r in session.run(
                        """
MATCH (p:Paper)
WHERE coalesce(p.ingested, false) = true
RETURN p.paper_id AS id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.doi AS doi,
       p.year AS year,
       coalesce(p.ingested, false) AS ingested
ORDER BY p.year DESC
LIMIT $limit
""",
                        limit=limit_papers,
                    )
                ]
            paper_ids = [p["id"] for p in base_nodes]
            edges = [
                dict(r)
                for r in session.run(
                    """
MATCH (p:Paper)-[c:CITES]->(q:Paper)
WHERE p.paper_id IN $paper_ids AND q.paper_id IS NOT NULL
RETURN p.paper_id AS source,
       q.paper_id AS target,
       c.total_mentions AS total_mentions,
       c.purpose_labels AS purpose_labels
ORDER BY c.total_mentions DESC
LIMIT $limit
""",
                    paper_ids=paper_ids,
                    limit=limit_edges,
                )
            ]
            target_ids = sorted({e.get("target") for e in edges if e.get("target")})
            stub_nodes: list[dict] = []
            if target_ids:
                stub_nodes = [
                    dict(r)
                    for r in session.run(
                        """
MATCH (p:Paper)
WHERE p.paper_id IN $ids
RETURN p.paper_id AS id,
       coalesce(p.paper_source, p.title, p.doi, p.paper_id) AS paper_source,
       p.title AS title,
       p.doi AS doi,
       p.year AS year,
       coalesce(p.ingested, false) AS ingested
""",
                        ids=target_ids,
                    )
                ]

            nodes_by_id: dict[str, dict] = {n["id"]: n for n in base_nodes}
            for n in stub_nodes:
                nodes_by_id.setdefault(n["id"], n)

            base_set = set(paper_ids)
            out_nodes: list[dict] = []
            for n in nodes_by_id.values():
                d = dict(n)
                d["in_scope"] = bool(d.get("id") in base_set)
                out_nodes.append(d)
            return {"nodes": out_nodes, "edges": edges}

    def search_papers(self, query: str, limit: int = 20, collection_id: str | None = None) -> list[dict]:
        q = (query or "").strip().lower()
        if not q:
            return []
        limit = max(1, min(200, int(limit)))
        cid = (collection_id or "").strip()
        if cid:
            cypher = """
MATCH (co:Collection {collection_id:$collection_id})-[:HAS_PAPER]->(p:Paper)
WHERE toLower(coalesce(p.doi,'')) CONTAINS $q
   OR toLower(coalesce(p.title,'')) CONTAINS $q
   OR toLower(coalesce(p.paper_source,'')) CONTAINS $q
RETURN p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.doi AS doi,
       p.year AS year,
       coalesce(p.ingested,false) AS ingested
ORDER BY coalesce(p.year,0) DESC, p.paper_id ASC
LIMIT $limit
"""
            params = {"q": q, "limit": limit, "collection_id": cid}
        else:
            cypher = """
MATCH (p:Paper)
WHERE toLower(coalesce(p.doi,'')) CONTAINS $q
   OR toLower(coalesce(p.title,'')) CONTAINS $q
   OR toLower(coalesce(p.paper_source,'')) CONTAINS $q
RETURN p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.doi AS doi,
       p.year AS year,
       coalesce(p.ingested,false) AS ingested
ORDER BY coalesce(p.year,0) DESC, p.paper_id ASC
LIMIT $limit
"""
            params = {"q": q, "limit": limit}
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, **params)]

    def get_neighborhood(
        self,
        paper_id: str,
        depth: int = 1,
        limit_nodes: int = 200,
        limit_edges: int = 400,
        collection_id: str | None = None,
    ) -> dict:
        # v1 only supports depth=1 (keeps the UX predictable)
        pid = str(paper_id or "").strip()
        if not pid:
            raise ValueError("paper_id required")
        depth = 1
        cid = (collection_id or "").strip()
        with self._driver.session() as session:
            center = session.run(
                """
MATCH (p:Paper {paper_id:$paper_id})
RETURN p.paper_id AS id,
       p.paper_source AS paper_source,
       p.title AS title,
       p.doi AS doi,
       p.year AS year,
       coalesce(p.ingested,false) AS ingested
""",
                paper_id=pid,
            ).single()
            if not center:
                raise KeyError(f"Paper not found: {pid}")

            # 1-hop cites (outgoing + incoming). collection_id is used only for node labeling (in_scope),
            # not for filtering, because users often need to expand across collection boundaries.
            edges = [
                dict(r)
                for r in session.run(
                    """
MATCH (p:Paper {paper_id:$paper_id})
OPTIONAL MATCH (p)-[c:CITES]->(q:Paper)
RETURN p.paper_id AS source,
       q.paper_id AS target,
       c.total_mentions AS total_mentions,
       c.purpose_labels AS purpose_labels
UNION
MATCH (p:Paper {paper_id:$paper_id})
OPTIONAL MATCH (r:Paper)-[c:CITES]->(p)
RETURN r.paper_id AS source,
       p.paper_id AS target,
       c.total_mentions AS total_mentions,
       c.purpose_labels AS purpose_labels
LIMIT $limit_edges
""",
                    paper_id=pid,
                    limit_edges=limit_edges,
                )
                if r.get("source") and r.get("target")
            ]
            scope_ids = set()
            if cid:
                scope_ids = set(
                    x.get("paper_id")
                    for x in session.run(
                        """
MATCH (co:Collection {collection_id:$collection_id})-[:HAS_PAPER]->(p:Paper)
RETURN p.paper_id AS paper_id
""",
                        collection_id=cid,
                    )
                )

            neighbor_ids = {pid}
            for e in edges:
                neighbor_ids.add(str(e.get("source")))
                neighbor_ids.add(str(e.get("target")))
            neighbor_ids_list = list(neighbor_ids)[: max(1, min(limit_nodes, 2000))]
            nodes = [
                dict(r)
                for r in session.run(
                    """
MATCH (p:Paper)
WHERE p.paper_id IN $ids
RETURN p.paper_id AS id,
       coalesce(p.paper_source, p.title, p.doi, p.paper_id) AS paper_source,
       p.title AS title,
       p.doi AS doi,
       p.year AS year,
       coalesce(p.ingested,false) AS ingested
""",
                    ids=neighbor_ids_list,
                )
            ]

            if cid:
                for n in nodes:
                    n["in_scope"] = bool(str(n.get("id")) in scope_ids)
            else:
                for n in nodes:
                    n["in_scope"] = True

            return {"nodes": nodes, "edges": edges, "center_id": pid, "depth": depth, "collection_id": cid or None}

    def list_claim_similarity_rows(self, paper_id: str | None = None, limit: int = 200000) -> list[dict]:
        """
        Return effective claim texts for similarity indexing.

        Notes:
        - Applies Paper-level human overrides/clears (human_claims_json / human_claims_cleared_json).
        - Only returns Claim nodes that exist in the graph (claim_id must be present).
        - Cleared/empty claims are omitted.
        """
        pid = (paper_id or "").strip()
        limit = max(1, min(500000, int(limit)))

        cypher = """
MATCH (p:Paper)
WHERE ($paper_id = '' OR p.paper_id = $paper_id)
MATCH (p)-[:HAS_CLAIM]->(cl:Claim)
RETURN p.paper_id AS paper_id,
       p.human_claims_json AS human_claims_json,
       p.human_claims_cleared_json AS human_claims_cleared_json,
       cl.claim_id AS claim_id,
       cl.claim_key AS claim_key,
       cl.text AS text
LIMIT $limit
"""
        with self._driver.session() as session:
            rows = [dict(r) for r in session.run(cypher, paper_id=pid, limit=limit)]

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

        by_paper: dict[str, tuple[dict, set[str]]] = {}
        out: list[dict] = []
        for r in rows:
            p_id = str(r.get("paper_id") or "").strip()
            if not p_id:
                continue
            if p_id not in by_paper:
                human = _safe_json(r.get("human_claims_json"), {})
                cleared = set(_safe_json(r.get("human_claims_cleared_json"), []))
                if not isinstance(human, dict):
                    human = {}
                by_paper[p_id] = (human, cleared)
            human, cleared = by_paper[p_id]

            claim_id = str(r.get("claim_id") or "").strip()
            if not claim_id:
                continue
            claim_key = str(r.get("claim_key") or "").strip()
            if not claim_key:
                continue
            if claim_key in cleared:
                continue
            txt = human.get(claim_key)
            effective = (str(txt) if txt is not None else str(r.get("text") or "")).strip()
            if not effective:
                continue
            out.append({"node_id": claim_id, "paper_id": p_id, "text": effective})
        return out

    def list_logic_step_similarity_rows(self, paper_id: str | None = None, limit: int = 50000) -> list[dict]:
        """
        Return effective logic-step summaries for similarity indexing.

        Notes:
        - Applies Paper-level human overrides/clears (human_logic_json / human_logic_cleared_json).
        - Cleared/empty steps are omitted.
        """
        pid = (paper_id or "").strip()
        limit = max(1, min(200000, int(limit)))
        cypher = """
MATCH (p:Paper)
WHERE ($paper_id = '' OR p.paper_id = $paper_id)
MATCH (p)-[:HAS_LOGIC_STEP]->(ls:LogicStep)
RETURN p.paper_id AS paper_id,
       p.human_logic_json AS human_logic_json,
       p.human_logic_cleared_json AS human_logic_cleared_json,
       ls.logic_step_id AS logic_step_id,
       ls.step_type AS step_type,
       ls.summary AS summary
LIMIT $limit
"""
        with self._driver.session() as session:
            rows = [dict(r) for r in session.run(cypher, paper_id=pid, limit=limit)]

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

        by_paper: dict[str, tuple[dict, set[str]]] = {}
        out: list[dict] = []
        for r in rows:
            p_id = str(r.get("paper_id") or "").strip()
            if not p_id:
                continue
            if p_id not in by_paper:
                human = _safe_json(r.get("human_logic_json"), {})
                cleared = set(_safe_json(r.get("human_logic_cleared_json"), []))
                if not isinstance(human, dict):
                    human = {}
                by_paper[p_id] = (human, cleared)
            human, cleared = by_paper[p_id]

            step_id = str(r.get("logic_step_id") or "").strip()
            if not step_id:
                continue
            step_type = str(r.get("step_type") or "").strip()
            if not step_type:
                continue
            if step_type in cleared:
                continue
            txt = human.get(step_type)
            effective = (str(txt) if txt is not None else str(r.get("summary") or "")).strip()
            if not effective:
                continue
            out.append({"node_id": step_id, "paper_id": p_id, "text": effective})
        return out

    def list_logic_step_structured_rows(self, paper_id: str | None = None, limit: int = 50000) -> list[dict]:
        pid = (paper_id or "").strip()
        limit = max(1, min(200000, int(limit)))
        cypher = """
MATCH (p:Paper)-[:HAS_LOGIC_STEP]->(ls:LogicStep)
WHERE ($paper_id = '' OR p.paper_id = $paper_id)
OPTIONAL MATCH (ls)-[:EVIDENCED_BY]->(ch:Chunk)
WITH p, ls, collect(DISTINCT ch)[0..12] AS chunks
RETURN 'logic_step' AS kind,
       ls.logic_step_id AS source_id,
       p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       ls.step_type AS step_type,
       ls.summary AS text,
       [ch IN chunks WHERE ch.chunk_id IS NOT NULL | ch.chunk_id] AS evidence_chunk_ids,
       coalesce(head([ch IN chunks WHERE trim(coalesce(ch.text, '')) <> '' | ch.text]), '') AS evidence_quote
ORDER BY p.paper_id ASC, coalesce(ls.order, 999) ASC, ls.logic_step_id ASC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, paper_id=pid, limit=limit)]

    def list_claim_structured_rows(self, paper_id: str | None = None, limit: int = 50000) -> list[dict]:
        pid = (paper_id or "").strip()
        limit = max(1, min(200000, int(limit)))
        cypher = """
MATCH (p:Paper)-[:HAS_CLAIM]->(cl:Claim)
WHERE ($paper_id = '' OR p.paper_id = $paper_id)
OPTIONAL MATCH (cl)-[:EVIDENCED_BY]->(ch:Chunk)
WITH p, cl, collect(DISTINCT ch)[0..12] AS chunks
RETURN 'claim' AS kind,
       cl.claim_id AS source_id,
       p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       cl.step_type AS step_type,
       cl.text AS text,
       cl.confidence AS confidence,
       [ch IN chunks WHERE ch.chunk_id IS NOT NULL | ch.chunk_id] AS evidence_chunk_ids,
       coalesce(cl.evidence_quote, head([ch IN chunks WHERE trim(coalesce(ch.text, '')) <> '' | ch.text]), '') AS evidence_quote
ORDER BY p.paper_id ASC, cl.claim_id ASC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, paper_id=pid, limit=limit)]

    def get_grounding_rows_for_structured_ids(self, ids: list[dict], limit: int = 200) -> list[dict]:
        limit = max(1, min(500, int(limit)))
        claim_ids: list[str] = []
        logic_ids: list[str] = []
        for item in ids or []:
            kind = str(item.get("kind") or item.get("source_kind") or "").strip().lower()
            ident = str(item.get("id") or item.get("source_id") or "").strip()
            if not ident:
                continue
            if kind == "claim":
                claim_ids.append(ident)
            elif kind in {"logic_step", "logic"}:
                logic_ids.append(ident)

        rows: list[dict] = []
        with self._driver.session() as session:
            if claim_ids:
                claim_cypher = """
UNWIND $claim_ids AS claim_id
MATCH (cl:Claim {claim_id: claim_id})
OPTIONAL MATCH (cl)-[:EVIDENCED_BY]->(ch:Chunk)
OPTIONAL MATCH (cl)-[:TRIGGERS_EVENT]->(ev:EvidenceEvent)
RETURN 'claim' AS source_kind,
       cl.claim_id AS source_id,
       coalesce(cl.evidence_quote, ch.text, cl.text) AS quote,
       ch.chunk_id AS chunk_id,
       ch.md_path AS md_path,
       ch.start_line AS start_line,
       ch.end_line AS end_line,
       NULL AS textbook_id,
       NULL AS chapter_id,
       ev.event_id AS evidence_event_id,
       ev.event_type AS evidence_event_type
LIMIT $limit
"""
                rows.extend(dict(r) for r in session.run(claim_cypher, claim_ids=claim_ids[:limit], limit=limit))

            if logic_ids and len(rows) < limit:
                logic_cypher = """
UNWIND $logic_ids AS logic_step_id
MATCH (ls:LogicStep {logic_step_id: logic_step_id})
OPTIONAL MATCH (ls)-[:EVIDENCED_BY]->(ch:Chunk)
RETURN 'logic_step' AS source_kind,
       ls.logic_step_id AS source_id,
       coalesce(ch.text, ls.summary) AS quote,
       ch.chunk_id AS chunk_id,
       ch.md_path AS md_path,
       ch.start_line AS start_line,
       ch.end_line AS end_line,
       NULL AS textbook_id,
       NULL AS chapter_id,
       NULL AS evidence_event_id,
       NULL AS evidence_event_type
LIMIT $limit
"""
                rows.extend(
                    dict(r)
                    for r in session.run(
                        logic_cypher,
                        logic_ids=logic_ids[: max(1, limit - len(rows))],
                        limit=max(1, limit - len(rows)),
                    )
                )

        deduped: list[dict] = []
        seen: set[tuple[str, str, str, str]] = set()
        for row in rows:
            quote = str(row.get("quote") or "").strip()
            if not quote:
                continue
            normalized = {
                "source_kind": str(row.get("source_kind") or "").strip(),
                "source_id": str(row.get("source_id") or "").strip(),
                "quote": quote,
                "chunk_id": str(row.get("chunk_id") or "").strip() or None,
                "md_path": str(row.get("md_path") or "").strip() or None,
                "start_line": row.get("start_line"),
                "end_line": row.get("end_line"),
                "textbook_id": str(row.get("textbook_id") or "").strip() or None,
                "chapter_id": str(row.get("chapter_id") or "").strip() or None,
                "evidence_event_id": str(row.get("evidence_event_id") or "").strip() or None,
                "evidence_event_type": str(row.get("evidence_event_type") or "").strip() or None,
            }
            key = (
                normalized["source_kind"],
                normalized["source_id"],
                normalized["chunk_id"] or normalized["chapter_id"] or "",
                normalized["quote"],
            )
            if key in seen or not normalized["source_id"]:
                continue
            seen.add(key)
            deduped.append(normalized)
            if len(deduped) >= limit:
                break
        return deduped

    def list_gap_like_claims(self, limit: int = 200, kinds: list[str] | None = None) -> list[dict]:
        limit = max(1, min(5000, int(limit)))
        use_kinds = [str(k).strip() for k in (kinds or ["Gap", "FutureWork", "Limitation", "Critique"]) if str(k).strip()]
        if not use_kinds:
            return []

        cypher = """
MATCH (p:Paper)-[:HAS_CLAIM]->(cl:Claim)
WHERE any(k IN coalesce(cl.kinds, []) WHERE k IN $kinds)
OPTIONAL MATCH (cl)-[:IN_GLOBAL_COMMUNITY]->(gc:GlobalCommunity)
OPTIONAL MATCH (cl)-[ev:EVIDENCED_BY]->(:Chunk)
RETURN cl.claim_id AS claim_id,
       cl.claim_key AS claim_key,
       cl.text AS text,
       cl.kinds AS kinds,
       cl.step_type AS step_type,
       coalesce(cl.confidence, 0.0) AS confidence,
       p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS paper_title,
       p.year AS paper_year,
       collect(DISTINCT gc.community_id) AS source_community_ids,
       count(DISTINCT ev) AS evidence_count
ORDER BY confidence DESC, evidence_count DESC, cl.claim_id ASC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, kinds=use_kinds, limit=limit)]

    def replace_similar_claim_edges_batch(self, items: list[dict], model: str, built_at: str, mode: str = "embedding") -> None:
        """
        Replace outgoing SIMILAR_CLAIM edges for each source claim.
        Input: [{"source": "<claim_id>", "targets": [{"target":"<claim_id>","score":0.9}, ...]}, ...]
        """
        cypher = """
UNWIND $items AS it
MATCH (a:Claim {claim_id: it.source})
OPTIONAL MATCH (a)-[r:SIMILAR_CLAIM]->(:Claim)
DELETE r
WITH it, a
UNWIND coalesce(it.targets, []) AS t
MATCH (b:Claim {claim_id: t.target})
MERGE (a)-[s:SIMILAR_CLAIM]->(b)
SET s.score = t.score,
    s.model = $model,
    s.mode = $mode,
    s.built_at = $built_at
"""
        mode_norm = str(mode or "embedding").strip().lower()
        if mode_norm not in {"embedding", "lexical"}:
            mode_norm = "embedding"
        with self._driver.session() as session:
            # chunk to avoid huge transactions
            batch = list(items or [])
            for i in range(0, len(batch), 200):
                session.run(cypher, items=batch[i : i + 200], model=str(model), mode=mode_norm, built_at=str(built_at))

    def replace_similar_logic_edges_batch(self, items: list[dict], model: str, built_at: str) -> None:
        """
        Replace outgoing SIMILAR_LOGIC edges for each source logic step.
        Input: [{"source": "<logic_step_id>", "targets": [{"target":"<logic_step_id>","score":0.9}, ...]}, ...]
        """
        cypher = """
UNWIND $items AS it
MATCH (a:LogicStep {logic_step_id: it.source})
OPTIONAL MATCH (a)-[r:SIMILAR_LOGIC]->(:LogicStep)
DELETE r
WITH it, a
UNWIND coalesce(it.targets, []) AS t
MATCH (b:LogicStep {logic_step_id: t.target})
MERGE (a)-[s:SIMILAR_LOGIC]->(b)
SET s.score = t.score,
    s.model = $model,
    s.built_at = $built_at
"""
        with self._driver.session() as session:
            batch = list(items or [])
            for i in range(0, len(batch), 200):
                session.run(cypher, items=batch[i : i + 200], model=str(model), built_at=str(built_at))

    def list_similar_claim_edges_in_papers(
        self,
        paper_ids: list[str],
        min_score: float = 0.0,
        limit_per_source: int = 2,
        limit_total: int = 4000,
    ) -> list[dict]:
        ids = [str(x).strip() for x in (paper_ids or []) if str(x).strip()]
        if not ids:
            return []
        limit_per_source = max(1, min(50, int(limit_per_source)))
        limit_total = max(1, min(20000, int(limit_total)))
        cypher = """
MATCH (p1:Paper)-[:HAS_CLAIM]->(a:Claim)-[s:SIMILAR_CLAIM]->(b:Claim)<-[:HAS_CLAIM]-(p2:Paper)
WHERE p1.paper_id IN $paper_ids
  AND p2.paper_id IN $paper_ids
  AND p1.paper_id <> p2.paper_id
  AND coalesce(s.score, 0.0) >= $min_score
WITH a, b, s
ORDER BY s.score DESC
WITH a, collect({target: b.claim_id, score: s.score})[0..$limit_per_source] AS tgts
UNWIND tgts AS t
RETURN a.claim_id AS source, t.target AS target, t.score AS score
LIMIT $limit_total
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, paper_ids=ids, min_score=float(min_score), limit_per_source=limit_per_source, limit_total=limit_total)]

    def list_similar_logic_edges_in_papers(
        self,
        paper_ids: list[str],
        min_score: float = 0.0,
        limit_per_source: int = 2,
        limit_total: int = 3000,
    ) -> list[dict]:
        ids = [str(x).strip() for x in (paper_ids or []) if str(x).strip()]
        if not ids:
            return []
        limit_per_source = max(1, min(50, int(limit_per_source)))
        limit_total = max(1, min(20000, int(limit_total)))
        cypher = """
MATCH (p1:Paper)-[:HAS_LOGIC_STEP]->(a:LogicStep)-[s:SIMILAR_LOGIC]->(b:LogicStep)<-[:HAS_LOGIC_STEP]-(p2:Paper)
WHERE p1.paper_id IN $paper_ids
  AND p2.paper_id IN $paper_ids
  AND p1.paper_id <> p2.paper_id
  AND coalesce(s.score, 0.0) >= $min_score
WITH a, b, s
ORDER BY s.score DESC
WITH a, collect({target: b.logic_step_id, score: s.score})[0..$limit_per_source] AS tgts
UNWIND tgts AS t
RETURN a.logic_step_id AS source, t.target AS target, t.score AS score
LIMIT $limit_total
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, paper_ids=ids, min_score=float(min_score), limit_per_source=limit_per_source, limit_total=limit_total)]

    def resolve_reference(self, ref_id: str, cited_paper: dict) -> None:
        cypher = """
MATCH (p:Paper)-[u:CITES_UNRESOLVED]->(re:ReferenceEntry {ref_id:$ref_id})
MERGE (q:Paper {paper_id:$cited_paper.paper_id})
ON CREATE SET q += $cited_paper
ON MATCH SET
    q.paper_id = $cited_paper.paper_id,
    q.doi = CASE
        WHEN $cited_paper.doi IS NULL OR trim(toString($cited_paper.doi)) = '' THEN q.doi
        ELSE $cited_paper.doi
    END,
    q.title = coalesce(q.title, $cited_paper.title),
    q.authors = coalesce(q.authors, $cited_paper.authors),
    q.year = coalesce(q.year, $cited_paper.year),
    q.abstract = coalesce(q.abstract, $cited_paper.abstract),
    q.paper_source = coalesce(q.paper_source, $cited_paper.paper_source),
    q.md_path = coalesce(q.md_path, $cited_paper.md_path)
MERGE (p)-[c:CITES]->(q)
SET c.total_mentions = u.total_mentions,
    c.evidence_chunk_ids = u.evidence_chunk_ids,
    c.evidence_spans = u.evidence_spans,
    c.ref_nums = u.ref_nums,
    c.purpose_labels = CASE
        WHEN c.purpose_labels IS NULL OR size(c.purpose_labels) = 0 THEN ['Background']
        ELSE c.purpose_labels
    END,
    c.purpose_scores = CASE
        WHEN c.purpose_scores IS NULL OR size(c.purpose_scores) = 0 THEN [0.2]
        ELSE c.purpose_scores
    END
DELETE u
SET re.resolved_doi = $cited_paper.doi,
    re.resolve_confidence = 1.0
"""
        with self._driver.session() as session:
            session.run(cypher, ref_id=ref_id, cited_paper=cited_paper)

    def update_reference_crossref_preview(
        self,
        ref_id: str,
        crossref_json: str | None,
        resolved_doi: str | None,
        resolve_confidence: float | None,
        resolved_title: str | None = None,
        resolved_year: int | None = None,
        resolved_venue: str | None = None,
        resolved_authors: list[str] | None = None,
    ) -> None:
        cypher = """
MATCH (re:ReferenceEntry {ref_id:$ref_id})
SET re.crossref_json = $crossref_json,
    re.resolved_doi = $resolved_doi,
    re.resolve_confidence = $resolve_confidence,
    re.resolved_title = $resolved_title,
    re.resolved_year = $resolved_year,
    re.resolved_venue = $resolved_venue,
    re.resolved_authors = $resolved_authors
"""
        with self._driver.session() as session:
            session.run(
                cypher,
                ref_id=ref_id,
                crossref_json=crossref_json,
                resolved_doi=resolved_doi,
                resolve_confidence=resolve_confidence,
                resolved_title=resolved_title,
                resolved_year=resolved_year,
                resolved_venue=resolved_venue,
                resolved_authors=list(resolved_authors or []),
            )

    def resolve_unresolved_reference_merge(
        self,
        ref_id: str,
        cited_paper: dict,
        crossref_json: str | None,
        confidence: float,
        max_evidence: int = 5,
    ) -> None:
        """
        Convert one unresolved cite into a resolved cite, merging into any existing CITES edge.

        Merge rules:
        - total_mentions: add
        - ref_nums / evidence_*: ordered union, cap evidence lists
        - purpose_labels/scores: keep existing (or empty arrays)
        - cited Paper fields: only fill missing values (never overwrite with null/empty)
        """
        doi = str(cited_paper.get("doi") or "").strip().lower()
        paper_id = str(cited_paper.get("paper_id") or "").strip() or (f"doi:{doi}" if doi else "")
        title = cited_paper.get("title")
        venue = cited_paper.get("venue")
        year = cited_paper.get("year")
        authors = cited_paper.get("authors") or []
        try:
            year_i = int(year) if year is not None else None
        except Exception:
            year_i = None

        max_evidence_idx = max(0, int(max_evidence) - 1)
        cypher = """
MATCH (p:Paper)-[u:CITES_UNRESOLVED]->(re:ReferenceEntry {ref_id:$ref_id})
MERGE (q:Paper {paper_id:$cited_paper_id})
SET q.doi = coalesce(q.doi, $doi)
SET q.title = coalesce(q.title, $title)
SET q.year = coalesce(q.year, $year)
SET q.venue = coalesce(q.venue, $venue)
SET q.authors = CASE WHEN q.authors IS NULL OR size(q.authors)=0 THEN $authors ELSE q.authors END
MERGE (p)-[c:CITES]->(q)
WITH p, q, c, u, re,
     coalesce(c.ref_nums, []) + coalesce(u.ref_nums, []) AS all_ref_nums,
     coalesce(c.evidence_chunk_ids, []) + coalesce(u.evidence_chunk_ids, []) AS all_evidence_chunk_ids,
     coalesce(c.evidence_spans, []) + coalesce(u.evidence_spans, []) AS all_evidence_spans
WITH p, q, c, u, re,
     reduce(acc=[], x IN all_ref_nums | CASE WHEN x IN acc THEN acc ELSE acc + x END) AS ref_nums_merged,
     reduce(acc=[], x IN all_evidence_chunk_ids | CASE WHEN x IN acc THEN acc ELSE acc + x END) AS evidence_chunk_ids_merged,
     reduce(acc=[], x IN all_evidence_spans | CASE WHEN x IN acc THEN acc ELSE acc + x END) AS evidence_spans_merged
SET c.total_mentions = coalesce(c.total_mentions, 0) + coalesce(u.total_mentions, 0),
    c.ref_nums = ref_nums_merged,
    c.evidence_chunk_ids = evidence_chunk_ids_merged[0..$max_evidence_idx],
    c.evidence_spans = evidence_spans_merged[0..$max_evidence_idx],
    c.purpose_labels = CASE
        WHEN c.purpose_labels IS NULL OR size(c.purpose_labels) = 0 THEN ['Background']
        ELSE c.purpose_labels
    END,
    c.purpose_scores = CASE
        WHEN c.purpose_scores IS NULL OR size(c.purpose_scores) = 0 THEN [0.2]
        ELSE c.purpose_scores
    END
DELETE u
SET re.resolved_doi = $doi,
    re.resolve_confidence = $confidence,
    re.crossref_json = $crossref_json,
    re.resolved_title = $title,
    re.resolved_year = $year,
    re.resolved_venue = $venue,
    re.resolved_authors = $authors
"""
        with self._driver.session() as session:
            session.run(
                cypher,
                ref_id=ref_id,
                cited_paper_id=paper_id,
                doi=doi or None,
                title=str(title) if title is not None else None,
                year=year_i,
                venue=str(venue) if venue is not None else None,
                authors=[str(a) for a in (authors or []) if str(a).strip()],
                confidence=float(confidence),
                crossref_json=crossref_json,
                max_evidence_idx=max_evidence_idx,
            )

    def update_cites_purposes(self, citing_paper_id: str, cited_paper_id: str, labels: list[str], scores: list[float]) -> None:
        cypher = """
MATCH (p:Paper {paper_id:$citing_paper_id})-[c:CITES]->(q:Paper {paper_id:$cited_paper_id})
SET c.purpose_labels = $labels,
    c.purpose_scores = $scores
"""
        with self._driver.session() as session:
            session.run(
                cypher,
                citing_paper_id=citing_paper_id,
                cited_paper_id=cited_paper_id,
                labels=labels,
                scores=scores,
            )

    def backfill_missing_citation_purposes(
        self,
        citing_paper_id: str,
        default_label: str = "Background",
        default_score: float = 0.2,
    ) -> int:
        """Backfill missing citation purpose labels for all CITES edges of a paper.

        Defense-in-depth: Ensures every CITES edge from a citing paper has non-empty
        purpose_labels and purpose_scores. This fixes edge cases where purpose labels
        were not set during initial ingestion or reference resolution.

        Args:
            citing_paper_id: Paper ID of the citing paper
            default_label: Default purpose label to use (default: "Background")
            default_score: Default confidence score (default: 0.2, range: 0.0-1.0)

        Returns:
            Number of CITES edges that were backfilled
        """
        pid = str(citing_paper_id or "").strip()
        if not pid:
            return 0

        # Validate and normalize inputs
        label = str(default_label or "").strip() or "Background"
        try:
            score = float(default_score)
        except (ValueError, TypeError):
            score = 0.2
        score = max(0.0, min(1.0, score))  # Clamp to [0.0, 1.0]

        cypher = """
MATCH (p:Paper {paper_id:$citing_paper_id})-[c:CITES]->(:Paper)
WHERE c.purpose_labels IS NULL OR size(c.purpose_labels) = 0
   OR c.purpose_scores IS NULL OR size(c.purpose_scores) = 0
SET c.purpose_labels = CASE
        WHEN c.purpose_labels IS NULL OR size(c.purpose_labels) = 0 THEN [$label]
        ELSE c.purpose_labels
    END,
    c.purpose_scores = CASE
        WHEN c.purpose_scores IS NULL OR size(c.purpose_scores) = 0 THEN [$score]
        ELSE c.purpose_scores
    END
RETURN count(c) AS updated
"""
        with self._driver.session() as session:
            result = session.run(cypher, citing_paper_id=pid, label=label, score=score)
            row = result.single()

        if not row:
            return 0
        return int(row["updated"] or 0)

    # 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
    # Textbook sub-graph CRUD
    # 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

    def upsert_textbook(
        self,
        textbook_id: str,
        title: str,
        authors: list[str] | None = None,
        year: int | None = None,
        edition: str | None = None,
        doc_type: str = "textbook",
        source_dir: str | None = None,
        total_chapters: int = 0,
    ) -> None:
        cypher = """
MERGE (t:Textbook {textbook_id: $textbook_id})
SET t.title          = $title,
    t.authors        = $authors,
    t.year           = $year,
    t.edition        = $edition,
    t.doc_type       = $doc_type,
    t.source_dir     = $source_dir,
    t.total_chapters = $total_chapters,
    t.ingested       = datetime()
"""
        with self._driver.session() as session:
            session.run(
                cypher,
                textbook_id=str(textbook_id),
                title=str(title or ""),
                authors=[str(a) for a in (authors or []) if str(a).strip()],
                year=int(year) if year is not None else None,
                edition=str(edition) if edition else None,
                doc_type=str(doc_type or "textbook"),
                source_dir=str(source_dir) if source_dir else None,
                total_chapters=int(total_chapters or 0),
            )

    def upsert_textbook_chapter(
        self,
        chapter_id: str,
        textbook_id: str,
        chapter_num: int,
        title: str,
        youtu_graph_file: str | None = None,
        entity_count: int = 0,
        relation_count: int = 0,
    ) -> None:
        cypher = """
MATCH (t:Textbook {textbook_id: $textbook_id})
MERGE (c:TextbookChapter {chapter_id: $chapter_id})
SET c.chapter_num      = $chapter_num,
    c.title            = $title,
    c.youtu_graph_file = $youtu_graph_file,
    c.entity_count     = $entity_count,
    c.relation_count   = $relation_count
MERGE (t)-[:HAS_CHAPTER]->(c)
"""
        with self._driver.session() as session:
            session.run(
                cypher,
                chapter_id=str(chapter_id),
                textbook_id=str(textbook_id),
                chapter_num=int(chapter_num),
                title=str(title or ""),
                youtu_graph_file=str(youtu_graph_file) if youtu_graph_file else None,
                entity_count=int(entity_count or 0),
                relation_count=int(relation_count or 0),
            )

    def create_knowledge_entities(self, entities: list[dict]) -> int:
        """Batch-create KnowledgeEntity nodes. Returns count created."""
        if not entities:
            return 0
        cypher = """
UNWIND $rows AS r
MERGE (e:KnowledgeEntity {entity_id: r.entity_id})
SET e.name              = r.name,
    e.entity_type       = r.entity_type,
    e.description       = r.description,
    e.attributes        = r.attributes,
    e.source_chapter_id = r.source_chapter_id
RETURN count(e) AS cnt
"""
        rows = []
        for ent in entities:
            eid = str(ent.get("entity_id") or "").strip()
            if not eid:
                continue
            rows.append({
                "entity_id": eid,
                "name": str(ent.get("name") or ""),
                "entity_type": str(ent.get("entity_type") or "unknown"),
                "description": str(ent.get("description") or ""),
                "attributes": str(ent.get("attributes") or "{}"),
                "source_chapter_id": str(ent.get("source_chapter_id") or ""),
            })
        if not rows:
            return 0
        total = 0
        batch_size = 200
        with self._driver.session() as session:
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                result = session.run(cypher, rows=batch)
                row = result.single()
                total += int(row["cnt"]) if row else 0
        return total

    def create_entity_relations(self, relations: list[dict]) -> int:
        """Batch-create RELATES_TO edges between KnowledgeEntity nodes."""
        if not relations:
            return 0
        cypher = """
UNWIND $rows AS r
MATCH (a:KnowledgeEntity {entity_id: r.start_id})
MATCH (b:KnowledgeEntity {entity_id: r.end_id})
MERGE (a)-[rel:RELATES_TO {rel_type: r.rel_type}]->(b)
RETURN count(rel) AS cnt
"""
        rows = []
        for rel in relations:
            sid = str(rel.get("start_id") or "").strip()
            eid = str(rel.get("end_id") or "").strip()
            if not sid or not eid:
                continue
            rows.append({
                "start_id": sid,
                "end_id": eid,
                "rel_type": str(rel.get("rel_type") or "related_to"),
            })
        if not rows:
            return 0
        total = 0
        batch_size = 200
        with self._driver.session() as session:
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                result = session.run(cypher, rows=batch)
                row = result.single()
                total += int(row["cnt"]) if row else 0
        return total

    def link_chapter_entities(self, chapter_id: str, entity_ids: list[str]) -> int:
        """Create HAS_ENTITY edges from TextbookChapter to KnowledgeEntity nodes."""
        if not entity_ids:
            return 0
        cypher = """
MATCH (c:TextbookChapter {chapter_id: $chapter_id})
UNWIND $entity_ids AS eid
MATCH (e:KnowledgeEntity {entity_id: eid})
MERGE (c)-[:HAS_ENTITY]->(e)
RETURN count(*) AS cnt
"""
        with self._driver.session() as session:
            result = session.run(cypher, chapter_id=str(chapter_id), entity_ids=[str(e) for e in entity_ids])
            row = result.single()
        return int(row["cnt"]) if row else 0

    def create_fusion_explains_edges(self, links: list[dict]) -> int:
        """Create or update EXPLAINS edges between LogicStep and KnowledgeEntity."""
        if not links:
            return 0
        cypher = """
UNWIND $rows AS r
MATCH (ls:LogicStep {logic_step_id: r.logic_step_id})
MATCH (e:KnowledgeEntity {entity_id: r.entity_id})
MERGE (ls)-[rel:EXPLAINS]->(e)
SET rel.score = coalesce(r.score, rel.score),
    rel.reasons = coalesce(r.reasons, rel.reasons),
    rel.evidence_chunk_ids = coalesce(r.evidence_chunk_ids, rel.evidence_chunk_ids),
    rel.source_chunk_id = CASE
        WHEN r.source_chunk_id IS NULL OR trim(toString(r.source_chunk_id)) = '' THEN rel.source_chunk_id
        ELSE r.source_chunk_id
    END,
    rel.evidence_quote = CASE
        WHEN r.evidence_quote IS NULL OR trim(toString(r.evidence_quote)) = '' THEN rel.evidence_quote
        ELSE r.evidence_quote
    END,
    rel.source_chapter_id = CASE
        WHEN r.source_chapter_id IS NULL OR trim(toString(r.source_chapter_id)) = '' THEN rel.source_chapter_id
        ELSE r.source_chapter_id
    END,
    rel.updated_at = datetime()
RETURN count(rel) AS cnt
"""
        rows = []
        for link in links:
            sid = str(link.get("logic_step_id") or "").strip()
            eid = str(link.get("entity_id") or "").strip()
            if not sid or not eid:
                continue
            rows.append(
                {
                    "logic_step_id": sid,
                    "entity_id": eid,
                    "score": float(link["score"]) if link.get("score") is not None else None,
                    "reasons": [str(x) for x in (link.get("reasons") or []) if str(x).strip()],
                    "evidence_chunk_ids": [
                        str(x) for x in (link.get("evidence_chunk_ids") or []) if str(x).strip()
                    ],
                    "source_chunk_id": str(link.get("source_chunk_id") or "").strip() or None,
                    "evidence_quote": str(link.get("evidence_quote") or "").strip() or None,
                    "source_chapter_id": str(link.get("source_chapter_id") or "").strip() or None,
                }
            )
        if not rows:
            return 0
        with self._driver.session() as session:
            result = session.run(cypher, rows=rows)
            row = result.single()
        return int(row["cnt"]) if row else 0

    def upsert_fusion_communities(self, communities: list[dict]) -> int:
        """Write FusionCommunity nodes and IN_COMMUNITY memberships."""
        if not communities:
            return 0

        cypher = """
UNWIND $rows AS r
MERGE (fc:FusionCommunity {community_id: r.community_id})
SET fc.title = r.title,
    fc.confidence = r.confidence,
    fc.representative_evidence = r.representative_evidence,
    fc.updated_at = datetime()
WITH fc, r
UNWIND r.member_ids AS member_id
OPTIONAL MATCH (ls:LogicStep {logic_step_id: member_id})
OPTIONAL MATCH (cl:Claim {claim_id: member_id})
OPTIONAL MATCH (ke:KnowledgeEntity {entity_id: member_id})
WITH fc, r, coalesce(ls, cl, ke) AS m
WHERE m IS NOT NULL
MERGE (m)-[ic:IN_COMMUNITY]->(fc)
SET ic.weight = r.weight
RETURN count(DISTINCT fc) AS cnt
"""
        rows = []
        for item in communities:
            cid = str(item.get("community_id") or "").strip()
            if not cid:
                continue
            members = [str(x).strip() for x in (item.get("member_ids") or []) if str(x).strip()]
            if not members:
                continue
            rows.append(
                {
                    "community_id": cid,
                    "title": str(item.get("title") or cid),
                    "confidence": float(item.get("confidence") or 0.0),
                    "representative_evidence": str(item.get("representative_evidence") or ""),
                    "member_ids": members,
                    "weight": float(item.get("weight") or 1.0),
                }
            )
        if not rows:
            return 0
        with self._driver.session() as session:
            result = session.run(cypher, rows=rows)
            row = result.single()
        return int(row["cnt"]) if row else 0

    def clear_global_communities(self) -> dict[str, int]:
        cypher = """
CALL {
    MATCH (gc:GlobalCommunity)
    RETURN count(gc) AS deleted_communities, collect(gc) AS communities
}
CALL {
    MATCH (gk:GlobalKeyword)
    RETURN count(gk) AS deleted_keywords, collect(gk) AS keywords
}
CALL {
    MATCH ()-[im:IN_GLOBAL_COMMUNITY]->(:GlobalCommunity)
    RETURN count(im) AS deleted_memberships, collect(im) AS memberships
}
CALL {
    MATCH (:GlobalCommunity)-[hk:HAS_GLOBAL_KEYWORD]->(:GlobalKeyword)
    RETURN count(hk) AS deleted_keyword_edges, collect(hk) AS keyword_edges
}
FOREACH (rel IN memberships | DELETE rel)
FOREACH (rel IN keyword_edges | DELETE rel)
FOREACH (node IN keywords | DETACH DELETE node)
FOREACH (node IN communities | DETACH DELETE node)
RETURN deleted_communities,
       deleted_keywords,
       deleted_memberships,
       deleted_keyword_edges
"""
        with self._driver.session() as session:
            row = session.run(cypher).single()
        return {
            "deleted_communities": int((row or {}).get("deleted_communities") or 0),
            "deleted_keywords": int((row or {}).get("deleted_keywords") or 0),
            "deleted_memberships": int((row or {}).get("deleted_memberships") or 0),
            "deleted_keyword_edges": int((row or {}).get("deleted_keyword_edges") or 0),
        }

    def clear_legacy_proposition_artifacts(self) -> dict[str, int]:
        cypher = """
CALL {
    MATCH (:Proposition)-[r:SUPPORTS|CHALLENGES|SUPERSEDES]->(:Proposition)
    RETURN count(r) AS deleted_relation_edges, collect(r) AS relation_edges
}
CALL {
    MATCH (pg:PropositionGroup)
    RETURN count(pg) AS deleted_proposition_groups, collect(pg) AS proposition_groups
}
CALL {
    MATCH (pr:Proposition)
    RETURN count(pr) AS deleted_propositions, collect(pr) AS propositions
}
FOREACH (rel IN relation_edges | DELETE rel)
FOREACH (node IN proposition_groups | DETACH DELETE node)
FOREACH (node IN propositions | DETACH DELETE node)
RETURN deleted_proposition_groups,
       deleted_propositions,
       deleted_relation_edges
"""
        with self._driver.session() as session:
            row = session.run(cypher).single()
        return {
            "deleted_proposition_groups": int((row or {}).get("deleted_proposition_groups") or 0),
            "deleted_propositions": int((row or {}).get("deleted_propositions") or 0),
            "deleted_relation_edges": int((row or {}).get("deleted_relation_edges") or 0),
        }

    def clear_legacy_discovery_artifacts(self) -> dict[str, dict[str, int]]:
        labels = [
            "KnowledgeGap",
            "ResearchQuestion",
            "ResearchQuestionCandidate",
            "FeedbackRecord",
            "KnowledgeGapSeed",
        ]
        deleted_labels: dict[str, int] = {}
        with self._driver.session() as session:
            for label in labels:
                row = session.run(
                    f"""
MATCH (n:{label})
WITH count(n) AS deleted_count, collect(n) AS rows
FOREACH (item IN rows | DETACH DELETE item)
RETURN deleted_count
"""
                ).single()
                deleted_labels[label] = int((row or {}).get("deleted_count") or 0)
        return {
            "deleted_labels": deleted_labels,
        }

    def upsert_global_communities(self, items: list[dict]) -> int:
        if not items:
            return 0
        cypher = """
UNWIND $rows AS r
MERGE (gc:GlobalCommunity {community_id: r.community_id})
SET gc.title = r.title,
    gc.summary = r.summary,
    gc.confidence = r.confidence,
    gc.member_count = r.member_count,
    gc.version = r.version,
    gc.built_at = r.built_at,
    gc.updated_at = datetime()
RETURN count(DISTINCT gc) AS cnt
"""
        rows = []
        for item in items:
            community_id = str(item.get("community_id") or "").strip()
            if not community_id:
                continue
            rows.append(
                {
                    "community_id": community_id,
                    "title": str(item.get("title") or community_id).strip() or community_id,
                    "summary": str(item.get("summary") or "").strip(),
                    "confidence": float(item.get("confidence") or 0.0),
                    "member_count": int(item.get("member_count") or 0),
                    "version": str(item.get("version") or settings.global_community_version).strip() or settings.global_community_version,
                    "built_at": str(item.get("built_at") or "").strip() or None,
                }
            )
        if not rows:
            return 0
        with self._driver.session() as session:
            row = session.run(cypher, rows=rows).single()
        return int((row or {}).get("cnt") or 0)

    def upsert_global_keywords(self, items: list[dict]) -> int:
        if not items:
            return 0
        cypher = """
UNWIND $rows AS r
MATCH (gc:GlobalCommunity {community_id: r.community_id})
MERGE (gk:GlobalKeyword {keyword_id: r.keyword_id})
SET gk.keyword = r.keyword,
    gk.weight = r.weight,
    gk.community_id = r.community_id,
    gk.updated_at = datetime()
MERGE (gc)-[hk:HAS_GLOBAL_KEYWORD]->(gk)
SET hk.rank = r.rank,
    hk.weight = r.weight
RETURN count(hk) AS cnt
"""
        rows = []
        for item in items:
            community_id = str(item.get("community_id") or "").strip()
            keyword_id = str(item.get("keyword_id") or "").strip()
            keyword = str(item.get("keyword") or "").strip()
            if not community_id or not keyword_id or not keyword:
                continue
            rows.append(
                {
                    "community_id": community_id,
                    "keyword_id": keyword_id,
                    "keyword": keyword,
                    "rank": int(item.get("rank") or 0),
                    "weight": float(item.get("weight") or 0.0),
                }
            )
        if not rows:
            return 0
        with self._driver.session() as session:
            row = session.run(cypher, rows=rows).single()
        return int((row or {}).get("cnt") or 0)

    def replace_global_memberships(self, items: list[dict]) -> int:
        if not items:
            return 0

        rows = []
        community_ids: list[str] = []
        seen_community_ids: set[str] = set()
        for item in items:
            community_id = str(item.get("community_id") or "").strip()
            member_id = str(item.get("member_id") or "").strip()
            member_kind = str(item.get("member_kind") or "").strip()
            if not community_id or not member_id:
                continue
            normalized_kind = member_kind.casefold()
            if normalized_kind in {"claim"}:
                member_kind = "Claim"
            elif normalized_kind in {"logicstep", "logic_step", "logic"}:
                member_kind = "LogicStep"
            elif normalized_kind in {"knowledgeentity", "knowledge_entity", "entity"}:
                member_kind = "KnowledgeEntity"
            rows.append(
                {
                    "community_id": community_id,
                    "member_id": member_id,
                    "member_kind": member_kind,
                    "weight": float(item.get("weight") or 0.0),
                }
            )
            if community_id not in seen_community_ids:
                seen_community_ids.add(community_id)
                community_ids.append(community_id)

        if not rows:
            return 0

        delete_cypher = """
MATCH (gc:GlobalCommunity)
WHERE gc.community_id IN $community_ids
OPTIONAL MATCH ()-[old:IN_GLOBAL_COMMUNITY]->(gc)
WITH collect(old) AS stale_edges
FOREACH (rel IN [edge IN stale_edges WHERE edge IS NOT NULL] | DELETE rel)
"""
        write_cypher = """
UNWIND $rows AS r
MATCH (gc:GlobalCommunity {community_id: r.community_id})
OPTIONAL MATCH (ls:LogicStep {logic_step_id: r.member_id})
OPTIONAL MATCH (cl:Claim {claim_id: r.member_id})
OPTIONAL MATCH (ke:KnowledgeEntity {entity_id: r.member_id})
WITH gc, r, coalesce(
    CASE WHEN r.member_kind = 'LogicStep' THEN ls END,
    CASE WHEN r.member_kind = 'Claim' THEN cl END,
    CASE WHEN r.member_kind = 'KnowledgeEntity' THEN ke END,
    ls,
    cl,
    ke
) AS member
WHERE member IS NOT NULL
MERGE (member)-[im:IN_GLOBAL_COMMUNITY]->(gc)
SET im.weight = r.weight,
    im.member_kind = r.member_kind
RETURN count(im) AS cnt
"""
        with self._driver.session() as session:
            session.run(delete_cypher, community_ids=community_ids)
            row = session.run(write_cypher, rows=rows).single()
        return int((row or {}).get("cnt") or 0)
    def list_global_community_rows(self, limit: int = 50000) -> list[dict]:
        cypher = """
MATCH (gc:GlobalCommunity)
OPTIONAL MATCH (gc)-[hk:HAS_GLOBAL_KEYWORD]->(gk:GlobalKeyword)
RETURN gc.community_id AS community_id,
       gc.title AS title,
       gc.summary AS summary,
       gc.confidence AS confidence,
       gc.member_count AS member_count,
       gc.version AS version,
       gc.built_at AS built_at,
       collect(DISTINCT gk.keyword) AS keywords
ORDER BY coalesce(gc.member_count, 0) DESC, gc.community_id ASC
LIMIT $limit
"""
        safe_limit = max(1, min(50000, int(limit)))
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, limit=safe_limit)]

    def list_global_community_members(self, community_id: str, limit: int = 200) -> list[dict]:
        cypher = """
MATCH (gc:GlobalCommunity {community_id: $community_id})<-[:IN_GLOBAL_COMMUNITY]-(member)
OPTIONAL MATCH (p:Paper {paper_id: member.paper_id})
WITH member,
     p,
     CASE
       WHEN member:LogicStep THEN member.logic_step_id
       WHEN member:Claim THEN member.claim_id
       WHEN member:KnowledgeEntity THEN member.entity_id
       ELSE toString(id(member))
     END AS member_id,
     CASE
       WHEN member:LogicStep THEN 'LogicStep'
       WHEN member:Claim THEN 'Claim'
       WHEN member:KnowledgeEntity THEN 'KnowledgeEntity'
       ELSE 'Node'
     END AS member_kind,
     coalesce(member.summary, member.text, member.name, member.title, '') AS text
RETURN member_id AS member_id,
       member_kind AS member_kind,
       text AS text,
       CASE
         WHEN member:LogicStep OR member:Claim THEN member.paper_id
         ELSE NULL
       END AS paper_id,
       CASE
         WHEN member:LogicStep OR member:Claim THEN coalesce(member.paper_source, p.paper_source)
         ELSE NULL
       END AS paper_source,
       CASE
         WHEN member:LogicStep OR member:Claim THEN coalesce(member.paper_title, p.title)
         ELSE NULL
       END AS paper_title,
       CASE
         WHEN member:LogicStep OR member:Claim THEN member.step_type
         ELSE NULL
       END AS step_type,
       CASE
         WHEN member:KnowledgeEntity THEN member.source_chapter_id
         ELSE NULL
       END AS source_chapter_id
ORDER BY member_kind ASC, member_id ASC
LIMIT $limit
"""
        cid = str(community_id or "").strip()
        if not cid:
            return []
        safe_limit = max(1, min(2000, int(limit)))
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, community_id=cid, limit=safe_limit)]

    def upsert_fusion_keywords(self, keyword_rows: list[dict]) -> int:
        """Write FusionKeyword nodes and HAS_KEYWORD edges from FusionCommunity."""
        if not keyword_rows:
            return 0
        cypher = """
UNWIND $rows AS r
MATCH (fc:FusionCommunity {community_id: r.community_id})
MERGE (fk:FusionKeyword {keyword_id: r.keyword_id})
SET fk.keyword = r.keyword,
    fk.weight = r.weight,
    fk.updated_at = datetime()
MERGE (fc)-[hk:HAS_KEYWORD]->(fk)
SET hk.rank = r.rank,
    hk.weight = r.weight
RETURN count(hk) AS cnt
"""
        rows = []
        for item in keyword_rows:
            cid = str(item.get("community_id") or "").strip()
            kid = str(item.get("keyword_id") or "").strip()
            keyword = str(item.get("keyword") or "").strip()
            if not cid or not kid or not keyword:
                continue
            rows.append(
                {
                    "community_id": cid,
                    "keyword_id": kid,
                    "keyword": keyword,
                    "rank": int(item.get("rank") or 0),
                    "weight": float(item.get("weight") or 0.0),
                }
            )
        if not rows:
            return 0
        with self._driver.session() as session:
            result = session.run(cypher, rows=rows)
            row = result.single()
        return int(row["cnt"]) if row else 0

    def list_logic_steps_for_fusion(self, paper_id: str | None = None, limit: int = 50000) -> list[dict]:
        cypher = """
MATCH (p:Paper)-[:HAS_LOGIC_STEP]->(ls:LogicStep)
WHERE $paper_id = '' OR p.paper_id = $paper_id
OPTIONAL MATCH (ls)-[:EVIDENCED_BY]->(ch:Chunk)
WITH p, ls, collect(DISTINCT ch.chunk_id) AS evidence_chunk_ids
RETURN ls.logic_step_id AS logic_step_id,
       p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       ls.step_type AS step_type,
       ls.summary AS summary,
       ls.order AS step_order,
       evidence_chunk_ids AS evidence_chunk_ids
ORDER BY p.paper_id ASC, coalesce(ls.order, 999) ASC, ls.logic_step_id ASC
LIMIT $limit
"""
        pid = str(paper_id or "").strip()
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, paper_id=pid, limit=int(limit))]

    def list_claims_for_fusion(self, paper_id: str | None = None, limit: int = 50000) -> list[dict]:
        cypher = """
MATCH (p:Paper)-[:HAS_CLAIM]->(cl:Claim)
WHERE $paper_id = '' OR p.paper_id = $paper_id
RETURN cl.claim_id AS claim_id,
       p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       cl.step_type AS step_type,
       cl.text AS text,
       cl.confidence AS confidence
ORDER BY p.paper_id ASC, cl.step_type ASC, cl.claim_id ASC
LIMIT $limit
"""
        pid = str(paper_id or "").strip()
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, paper_id=pid, limit=int(limit))]

    def list_textbook_entities_for_fusion(self, textbook_id: str | None = None, limit: int = 50000) -> list[dict]:
        cypher = """
MATCH (t:Textbook)-[:HAS_CHAPTER]->(c:TextbookChapter)-[:HAS_ENTITY]->(e:KnowledgeEntity)
WHERE $textbook_id = '' OR t.textbook_id = $textbook_id
RETURN DISTINCT e.entity_id AS entity_id,
       e.name AS name,
       e.entity_type AS entity_type,
       e.description AS description,
       coalesce(e.source_chapter_id, c.chapter_id) AS source_chapter_id
ORDER BY e.name ASC
LIMIT $limit
"""
        tid = str(textbook_id or "").strip()
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, textbook_id=tid, limit=int(limit))]

    def list_textbook_relations_for_fusion(self, textbook_id: str | None = None, limit: int = 100000) -> list[dict]:
        cypher = """
MATCH (t:Textbook)-[:HAS_CHAPTER]->(:TextbookChapter)-[:HAS_ENTITY]->(e1:KnowledgeEntity)
MATCH (e1)-[r:RELATES_TO]->(e2:KnowledgeEntity)
WHERE $textbook_id = '' OR t.textbook_id = $textbook_id
RETURN DISTINCT e1.entity_id AS start_id,
       e2.entity_id AS end_id,
       r.rel_type AS rel_type,
       r.confidence AS confidence,
       r.source_chunk_id AS source_chunk_id,
       r.evidence_quote AS evidence_quote
LIMIT $limit
"""
        tid = str(textbook_id or "").strip()
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, textbook_id=tid, limit=int(limit))]

    def list_fusion_graph(self, limit_nodes: int = 1000, limit_edges: int = 3000) -> dict[str, list[dict]]:
        cypher_nodes = """
MATCH (n)
WHERE n:LogicStep OR n:Claim OR n:KnowledgeEntity OR n:FusionCommunity OR n:FusionKeyword
RETURN
  CASE
    WHEN n:LogicStep THEN n.logic_step_id
    WHEN n:Claim THEN n.claim_id
    WHEN n:KnowledgeEntity THEN n.entity_id
    WHEN n:FusionCommunity THEN n.community_id
    WHEN n:FusionKeyword THEN n.keyword_id
    ELSE toString(id(n))
  END AS id,
  CASE
    WHEN n:LogicStep THEN 'LogicStep'
    WHEN n:Claim THEN 'Claim'
    WHEN n:KnowledgeEntity THEN 'KnowledgeEntity'
    WHEN n:FusionCommunity THEN 'FusionCommunity'
    WHEN n:FusionKeyword THEN 'FusionKeyword'
    ELSE 'Node'
  END AS label,
  coalesce(n.summary, n.text, n.name, n.title, n.keyword, '') AS text
LIMIT $limit_nodes
"""
        cypher_edges = """
MATCH (a)-[r]->(b)
WHERE type(r) IN ['EXPLAINS', 'RELATES_TO', 'IN_COMMUNITY', 'HAS_KEYWORD', 'HAS_CLAIM']
RETURN
  CASE
    WHEN a:LogicStep THEN a.logic_step_id
    WHEN a:Claim THEN a.claim_id
    WHEN a:KnowledgeEntity THEN a.entity_id
    WHEN a:FusionCommunity THEN a.community_id
    WHEN a:FusionKeyword THEN a.keyword_id
    ELSE toString(id(a))
  END AS source,
  CASE
    WHEN b:LogicStep THEN b.logic_step_id
    WHEN b:Claim THEN b.claim_id
    WHEN b:KnowledgeEntity THEN b.entity_id
    WHEN b:FusionCommunity THEN b.community_id
    WHEN b:FusionKeyword THEN b.keyword_id
    ELSE toString(id(b))
  END AS target,
  type(r) AS type,
  coalesce(r.score, r.weight, r.rank, 0.0) AS weight,
  r.reasons AS reasons
LIMIT $limit_edges
"""
        with self._driver.session() as session:
            nodes = [dict(r) for r in session.run(cypher_nodes, limit_nodes=int(limit_nodes))]
            edges = [dict(r) for r in session.run(cypher_edges, limit_edges=int(limit_edges))]
        return {"nodes": nodes, "edges": edges}

    def list_fusion_sections_for_paper(self, paper_id: str) -> list[dict]:
        cypher = """
MATCH (p:Paper {paper_id: $paper_id})-[:HAS_LOGIC_STEP]->(ls:LogicStep)
OPTIONAL MATCH (ls)-[ex:EXPLAINS]->(:KnowledgeEntity)
RETURN ls.logic_step_id AS logic_step_id,
       ls.step_type AS step_type,
       ls.summary AS summary,
       ls.order AS step_order,
       count(ex) AS basics_count,
       max(ex.score) AS top_score
ORDER BY coalesce(ls.order, 999) ASC, ls.step_type ASC
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, paper_id=str(paper_id))]

    def list_fusion_basics_for_section(self, paper_id: str, step_type: str, limit: int = 50) -> list[dict]:
        cypher = """
MATCH (p:Paper {paper_id: $paper_id})-[:HAS_LOGIC_STEP]->(ls:LogicStep)
WHERE ls.step_type = $step_type
MATCH (ls)-[ex:EXPLAINS]->(ke:KnowledgeEntity)
OPTIONAL MATCH (tc:TextbookChapter {chapter_id: coalesce(ex.source_chapter_id, ke.source_chapter_id)})
OPTIONAL MATCH (tb:Textbook)-[:HAS_CHAPTER]->(tc)
RETURN ls.logic_step_id AS logic_step_id,
       ls.step_type AS step_type,
       ke.entity_id AS entity_id,
       ke.name AS entity_name,
       ke.entity_type AS entity_type,
       ke.description AS description,
       ex.score AS score,
       ex.reasons AS reasons,
       ex.evidence_chunk_ids AS evidence_chunk_ids,
       ex.source_chunk_id AS source_chunk_id,
       ex.evidence_quote AS evidence_quote,
       tb.textbook_id AS textbook_id,
       tb.title AS textbook_title,
       tc.chapter_id AS chapter_id,
       tc.title AS chapter_title
ORDER BY coalesce(ex.score, 0.0) DESC, ke.name ASC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [
                dict(r)
                for r in session.run(
                    cypher,
                    paper_id=str(paper_id),
                    step_type=str(step_type),
                    limit=int(limit),
                )
            ]

    def list_fusion_basics_by_paper_sources(self, paper_sources: list[str], limit: int = 200) -> list[dict]:
        if not paper_sources:
            return []
        cypher = """
MATCH (p:Paper)-[:HAS_LOGIC_STEP]->(ls:LogicStep)-[ex:EXPLAINS]->(ke:KnowledgeEntity)
WHERE p.paper_source IN $paper_sources
OPTIONAL MATCH (tc:TextbookChapter {chapter_id: coalesce(ex.source_chapter_id, ke.source_chapter_id)})
OPTIONAL MATCH (tb:Textbook)-[:HAS_CHAPTER]->(tc)
RETURN p.paper_source AS paper_source,
       p.paper_id AS paper_id,
       ls.logic_step_id AS logic_step_id,
       ls.step_type AS step_type,
       ke.entity_id AS entity_id,
       ke.name AS entity_name,
       ke.entity_type AS entity_type,
       ke.description AS description,
       ex.score AS score,
       ex.reasons AS reasons,
       ex.evidence_chunk_ids AS evidence_chunk_ids,
       ex.source_chunk_id AS source_chunk_id,
       ex.evidence_quote AS evidence_quote,
       ex.source_chapter_id AS source_chapter_id,
       tb.textbook_id AS textbook_id,
       tb.title AS textbook_title,
       tc.chapter_id AS chapter_id,
       tc.chapter_num AS chapter_num,
       tc.title AS chapter_title
ORDER BY coalesce(ex.score, 0.0) DESC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [
                dict(r)
                for r in session.run(
                    cypher,
                    paper_sources=[str(x) for x in paper_sources if str(x).strip()],
                    limit=int(limit),
                )
            ]

    def list_textbooks(self, limit: int = 100) -> list[dict]:
        cypher = """
MATCH (t:Textbook)
OPTIONAL MATCH (t)-[:HAS_CHAPTER]->(c:TextbookChapter)
WITH t, count(c) AS ch_count,
     coalesce(sum(c.entity_count), 0) AS total_entities
RETURN t.textbook_id   AS textbook_id,
       t.title          AS title,
       t.authors        AS authors,
       t.year           AS year,
       t.edition        AS edition,
       t.doc_type       AS doc_type,
       t.total_chapters AS total_chapters,
       ch_count         AS chapter_count,
       total_entities   AS entity_count,
       t.ingested       AS ingested
ORDER BY t.ingested DESC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, limit=int(limit))]

    def get_textbook_detail(self, textbook_id: str) -> dict:
        cypher_tb = """
MATCH (t:Textbook {textbook_id: $textbook_id})
RETURN t.textbook_id   AS textbook_id,
       t.title          AS title,
       t.authors        AS authors,
       t.year           AS year,
       t.edition        AS edition,
       t.doc_type       AS doc_type,
       t.source_dir     AS source_dir,
       t.total_chapters AS total_chapters,
       t.ingested       AS ingested
"""
        cypher_ch = """
MATCH (t:Textbook {textbook_id: $textbook_id})-[:HAS_CHAPTER]->(c:TextbookChapter)
RETURN c.chapter_id      AS chapter_id,
       c.chapter_num     AS chapter_num,
       c.title           AS title,
       c.entity_count    AS entity_count,
       c.relation_count  AS relation_count,
       c.youtu_graph_file AS youtu_graph_file
ORDER BY c.chapter_num
"""
        with self._driver.session() as session:
            row = session.run(cypher_tb, textbook_id=str(textbook_id)).single()
            if not row:
                raise KeyError(f"Textbook not found: {textbook_id}")
            tb = dict(row)
            chapters = [dict(r) for r in session.run(cypher_ch, textbook_id=str(textbook_id))]
        tb["chapters"] = chapters
        return tb

    def get_chapter_entities(self, chapter_id: str, limit: int = 500) -> dict:
        cypher_ents = """
MATCH (c:TextbookChapter {chapter_id: $chapter_id})-[:HAS_ENTITY]->(e:KnowledgeEntity)
RETURN e.entity_id   AS entity_id,
       e.name        AS name,
       e.entity_type AS entity_type,
       e.description AS description,
       e.attributes  AS attributes
ORDER BY e.name
LIMIT $limit
"""
        cypher_rels = """
MATCH (c:TextbookChapter {chapter_id: $chapter_id})-[:HAS_ENTITY]->(e1:KnowledgeEntity)
MATCH (e1)-[r:RELATES_TO]->(e2:KnowledgeEntity)<-[:HAS_ENTITY]-(c)
RETURN e1.entity_id AS source_id,
       e2.entity_id AS target_id,
       r.rel_type   AS rel_type
"""
        with self._driver.session() as session:
            entities = [dict(r) for r in session.run(cypher_ents, chapter_id=str(chapter_id), limit=int(limit))]
            relations = [dict(r) for r in session.run(cypher_rels, chapter_id=str(chapter_id))]
        return {"entities": entities, "relations": relations}

    def get_textbook_graph_snapshot(self, textbook_id: str, entity_limit: int = 260, edge_limit: int = 520) -> dict:
        detail = self.get_textbook_detail(textbook_id)
        cypher_counts = """
MATCH (t:Textbook {textbook_id: $textbook_id})-[:HAS_CHAPTER]->(:TextbookChapter)-[:HAS_ENTITY]->(e:KnowledgeEntity)
RETURN count(DISTINCT e) AS entity_total
"""
        cypher_relation_count = """
MATCH (t:Textbook {textbook_id: $textbook_id})-[:HAS_CHAPTER]->(:TextbookChapter)-[:HAS_ENTITY]->(a:KnowledgeEntity)
MATCH (a)-[r:RELATES_TO]->(b:KnowledgeEntity)
RETURN count(DISTINCT r) AS relation_total
"""
        cypher_relations = """
MATCH (t:Textbook {textbook_id: $textbook_id})-[:HAS_CHAPTER]->(:TextbookChapter)-[:HAS_ENTITY]->(a:KnowledgeEntity)
MATCH (a)-[r:RELATES_TO]->(b:KnowledgeEntity)
MATCH (t)-[:HAS_CHAPTER]->(:TextbookChapter)-[:HAS_ENTITY]->(b)
RETURN DISTINCT a.entity_id AS source_id,
       b.entity_id AS target_id,
       r.rel_type AS rel_type
LIMIT $edge_limit
"""
        cypher_entities_by_ids = """
MATCH (e:KnowledgeEntity)
WHERE e.entity_id IN $entity_ids
OPTIONAL MATCH (c:TextbookChapter {chapter_id: e.source_chapter_id})
RETURN e.entity_id AS entity_id,
       e.name AS name,
       e.entity_type AS entity_type,
       e.description AS description,
       e.attributes AS attributes,
       coalesce(e.source_chapter_id, c.chapter_id) AS source_chapter_id
"""
        with self._driver.session() as session:
            entity_total_row = session.run(cypher_counts, textbook_id=str(textbook_id)).single()
            relation_total_row = session.run(cypher_relation_count, textbook_id=str(textbook_id)).single()

        entity_total = int(entity_total_row["entity_total"]) if entity_total_row else 0
        relation_total = int(relation_total_row["relation_total"]) if relation_total_row else 0
        raw_edge_limit = max(int(edge_limit) * 10, min(relation_total, 6000))
        with self._driver.session() as session:
            raw_relations = [dict(r) for r in session.run(cypher_relations, textbook_id=str(textbook_id), edge_limit=raw_edge_limit)]
            relation_entity_ids = sorted(
                {
                    str(rel.get("source_id") or "").strip()
                    for rel in raw_relations
                    if str(rel.get("source_id") or "").strip()
                }
                | {
                    str(rel.get("target_id") or "").strip()
                    for rel in raw_relations
                    if str(rel.get("target_id") or "").strip()
                }
            )
            raw_entities = (
                [dict(r) for r in session.run(cypher_entities_by_ids, entity_ids=relation_entity_ids)]
                if relation_entity_ids
                else []
            )
        if not raw_entities:
            raw_entity_limit = max(int(entity_limit) * 10, min(entity_total or int(entity_limit) * 10, 1600))
            raw_entities = self.list_textbook_entities_for_fusion(textbook_id=textbook_id, limit=raw_entity_limit)
            raw_relations = self.list_textbook_relations_for_fusion(textbook_id=textbook_id, limit=raw_edge_limit)
        entities, relations = sample_connected_graph_rows(
            raw_entities,
            raw_relations,
            entity_limit=entity_limit,
            edge_limit=edge_limit,
        )
        communities = build_community_rows(entities, relations)
        return {
            "scope": "textbook",
            "textbook": {
                "textbook_id": detail.get("textbook_id"),
                "title": detail.get("title"),
            },
            "chapters": detail.get("chapters") or [],
            "entities": entities,
            "relations": relations,
            "communities": communities,
            "stats": {
                "entity_total": entity_total,
                "relation_total": relation_total,
                "community_total": len(communities),
                "truncated": entity_total > len(entities) or relation_total > len(relations),
            },
        }

    def get_chapter_graph_snapshot(self, chapter_id: str, entity_limit: int = 220, edge_limit: int = 420) -> dict:
        cypher_chapter = """
MATCH (c:TextbookChapter {chapter_id: $chapter_id})
OPTIONAL MATCH (t:Textbook)-[:HAS_CHAPTER]->(c)
RETURN c.chapter_id AS chapter_id,
       c.chapter_num AS chapter_num,
       c.title AS title,
       t.textbook_id AS textbook_id,
       t.title AS textbook_title
"""
        cypher_entities = """
MATCH (c:TextbookChapter {chapter_id: $chapter_id})-[:HAS_ENTITY]->(e:KnowledgeEntity)
OPTIONAL MATCH (e)-[r:RELATES_TO]-(:KnowledgeEntity)
WITH c, e, count(r) AS degree
RETURN e.entity_id AS entity_id,
       e.name AS name,
       e.entity_type AS entity_type,
       e.description AS description,
       e.attributes AS attributes,
       coalesce(e.source_chapter_id, c.chapter_id) AS source_chapter_id,
       degree AS degree
ORDER BY degree DESC, e.name ASC
LIMIT $entity_limit
"""
        cypher_relations = """
MATCH (a:KnowledgeEntity)-[r:RELATES_TO]->(b:KnowledgeEntity)
WHERE a.entity_id IN $entity_ids AND b.entity_id IN $entity_ids
RETURN a.entity_id AS source_id,
       b.entity_id AS target_id,
       r.rel_type AS rel_type
ORDER BY source_id ASC, target_id ASC, rel_type ASC
LIMIT $edge_limit
"""
        cypher_counts = """
MATCH (c:TextbookChapter {chapter_id: $chapter_id})-[:HAS_ENTITY]->(e:KnowledgeEntity)
RETURN count(DISTINCT e) AS entity_total
"""
        cypher_relation_count = """
MATCH (c:TextbookChapter {chapter_id: $chapter_id})-[:HAS_ENTITY]->(a:KnowledgeEntity)
MATCH (a)-[r:RELATES_TO]->(b:KnowledgeEntity)<-[:HAS_ENTITY]-(c)
RETURN count(DISTINCT r) AS relation_total
"""
        with self._driver.session() as session:
            chapter_row = session.run(cypher_chapter, chapter_id=str(chapter_id)).single()
            if not chapter_row:
                raise KeyError(f"Chapter not found: {chapter_id}")
            entities = [dict(r) for r in session.run(cypher_entities, chapter_id=str(chapter_id), entity_limit=int(entity_limit))]
            entity_ids = [str(item.get("entity_id") or "").strip() for item in entities if str(item.get("entity_id") or "").strip()]
            relations = (
                [dict(r) for r in session.run(cypher_relations, entity_ids=entity_ids, edge_limit=int(edge_limit))]
                if entity_ids
                else []
            )
            entity_total_row = session.run(cypher_counts, chapter_id=str(chapter_id)).single()
            relation_total_row = session.run(cypher_relation_count, chapter_id=str(chapter_id)).single()

        chapter = dict(chapter_row)
        communities = build_community_rows(entities, relations)
        entity_total = int(entity_total_row["entity_total"]) if entity_total_row else len(entities)
        relation_total = int(relation_total_row["relation_total"]) if relation_total_row else len(relations)
        return {
            "scope": "chapter",
            "textbook": {
                "textbook_id": chapter.get("textbook_id"),
                "title": chapter.get("textbook_title"),
            },
            "chapter": {
                "chapter_id": chapter.get("chapter_id"),
                "chapter_num": chapter.get("chapter_num"),
                "title": chapter.get("title"),
            },
            "entities": entities,
            "relations": relations,
            "communities": communities,
            "stats": {
                "entity_total": entity_total,
                "relation_total": relation_total,
                "community_total": len(communities),
                "truncated": entity_total > len(entities) or relation_total > len(relations),
            },
        }

    def get_textbook_entities(self, textbook_id: str, limit: int = 2000) -> list[dict]:
        cypher = """
MATCH (t:Textbook {textbook_id: $textbook_id})-[:HAS_CHAPTER]->(c:TextbookChapter)-[:HAS_ENTITY]->(e:KnowledgeEntity)
WITH DISTINCT e, c
RETURN e.entity_id   AS entity_id,
       e.name        AS name,
       e.entity_type AS entity_type,
       e.description AS description,
       e.attributes  AS attributes,
       c.chapter_id  AS chapter_id,
       c.title       AS chapter_title
ORDER BY c.chapter_num, e.name
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, textbook_id=str(textbook_id), limit=int(limit))]

    def delete_textbook(self, textbook_id: str) -> dict:
        """Cascade-delete a textbook within a single transaction.

        Only deletes entities exclusively owned by this textbook (not shared
        with other textbooks).
        """
        def _tx(tx):
            # 1) Delete entities that belong ONLY to this textbook's chapters
            r1 = tx.run("""
MATCH (t:Textbook {textbook_id: $tid})-[:HAS_CHAPTER]->(c:TextbookChapter)-[:HAS_ENTITY]->(e:KnowledgeEntity)
WHERE NOT EXISTS {
    MATCH (other:TextbookChapter)-[:HAS_ENTITY]->(e)
    WHERE other.chapter_id <> c.chapter_id
    AND NOT EXISTS { MATCH (t)-[:HAS_CHAPTER]->(other) }
}
DETACH DELETE e
RETURN count(e) AS cnt
""", tid=str(textbook_id)).single()
            # 2) Delete chapters
            r2 = tx.run("""
MATCH (t:Textbook {textbook_id: $tid})-[:HAS_CHAPTER]->(c:TextbookChapter)
DETACH DELETE c
RETURN count(c) AS cnt
""", tid=str(textbook_id)).single()
            # 3) Delete textbook node
            r3 = tx.run("""
MATCH (t:Textbook {textbook_id: $tid})
DETACH DELETE t
RETURN count(t) AS cnt
""", tid=str(textbook_id)).single()
            return {
                "deleted_entities": int(r1["cnt"]) if r1 else 0,
                "deleted_chapters": int(r2["cnt"]) if r2 else 0,
                "deleted_textbook": int(r3["cnt"]) if r3 else 0,
            }

        with self._driver.session() as session:
            return session.execute_write(_tx)
