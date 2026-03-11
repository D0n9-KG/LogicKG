from __future__ import annotations

import json
import hashlib
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from neo4j import GraphDatabase

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


def normalize_proposition_text(text: str) -> str:
    s = _WS_RE.sub(" ", (text or "").strip().lower())
    while s and s[-1] in ".;銆傦紱":
        s = s[:-1].rstrip()
    return s


def _author_id_for_name(name: str) -> str:
    normalized = _WS_RE.sub(" ", str(name or "").strip().lower())
    normalized = normalized.replace(".", " ")
    normalized = _WS_RE.sub(" ", normalized).strip()
    if not normalized:
        return ""
    digest = hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"author:{digest}"


def proposition_key_for_claim(text: str, step_type: str | None = None, kinds: list[str] | None = None) -> str:
    """
    Generate deterministic proposition key based ONLY on normalized text.

    Assertion Layer (P1): Text-only identity ensures that identical claims
    from different reasoning steps or with different kinds are properly
    deduplicated. step_type and kinds are now tracked separately in the
    step_types_seen and kinds_seen arrays on the Proposition node.

    Parameters kept for backward compatibility but are ignored in hash calculation.
    """
    base = normalize_proposition_text(text)
    # Text-only hash for deterministic Assertion Layer identity
    raw = base.encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()[:24]


def proposition_id_for_key(prop_key: str) -> str:
    raw = ("proposition\0" + str(prop_key or "")).encode("utf-8", errors="ignore")
    return hashlib.sha256(raw).hexdigest()[:24]


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
        "prop_ids": [],
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
        elif key == "PR":
            bucket = "prop_ids"
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
            "CREATE CONSTRAINT proposition_id_unique IF NOT EXISTS FOR (pr:Proposition) REQUIRE pr.prop_id IS UNIQUE",
            "CREATE CONSTRAINT proposition_key_unique IF NOT EXISTS FOR (pr:Proposition) REQUIRE pr.prop_key IS UNIQUE",
            "CREATE CONSTRAINT proposition_group_id_unique IF NOT EXISTS FOR (pg:PropositionGroup) REQUIRE pg.group_id IS UNIQUE",
            "CREATE CONSTRAINT evidence_event_id_unique IF NOT EXISTS FOR (ev:EvidenceEvent) REQUIRE ev.event_id IS UNIQUE",
            "CREATE CONSTRAINT figure_id_unique IF NOT EXISTS FOR (f:Figure) REQUIRE f.figure_id IS UNIQUE",
            "CREATE CONSTRAINT collection_id_unique IF NOT EXISTS FOR (co:Collection) REQUIRE co.collection_id IS UNIQUE",
            "CREATE CONSTRAINT author_id_unique IF NOT EXISTS FOR (a:Author) REQUIRE a.author_id IS UNIQUE",
            "CREATE INDEX paper_doi IF NOT EXISTS FOR (p:Paper) ON (p.doi)",
            "CREATE INDEX paper_year IF NOT EXISTS FOR (p:Paper) ON (p.year)",
            "CREATE INDEX paper_ingested IF NOT EXISTS FOR (p:Paper) ON (p.ingested)",
            "CREATE INDEX author_name IF NOT EXISTS FOR (a:Author) ON (a.name)",
            "CREATE INDEX proposition_state IF NOT EXISTS FOR (pr:Proposition) ON (pr.current_state)",
            "CREATE INDEX proposition_score IF NOT EXISTS FOR (pr:Proposition) ON (pr.current_score)",
            "CREATE INDEX evidence_event_type IF NOT EXISTS FOR (ev:EvidenceEvent) ON (ev.event_type)",
            "CREATE INDEX evidence_event_status IF NOT EXISTS FOR (ev:EvidenceEvent) ON (ev.status)",
            "CREATE INDEX collection_name IF NOT EXISTS FOR (co:Collection) ON (co.name)",
            # 鈹€鈹€ Textbook sub-graph constraints & indexes 鈹€鈹€
            "CREATE CONSTRAINT textbook_id_unique IF NOT EXISTS FOR (t:Textbook) REQUIRE t.textbook_id IS UNIQUE",
            "CREATE CONSTRAINT chapter_id_unique IF NOT EXISTS FOR (tc:TextbookChapter) REQUIRE tc.chapter_id IS UNIQUE",
            "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (ke:KnowledgeEntity) REQUIRE ke.entity_id IS UNIQUE",
            "CREATE CONSTRAINT global_community_id_unique IF NOT EXISTS FOR (gc:GlobalCommunity) REQUIRE gc.community_id IS UNIQUE",
            "CREATE CONSTRAINT global_keyword_id_unique IF NOT EXISTS FOR (gk:GlobalKeyword) REQUIRE gk.keyword_id IS UNIQUE",
            "CREATE CONSTRAINT rq_candidate_id_unique IF NOT EXISTS FOR (rq:ResearchQuestionCandidate) REQUIRE rq.candidate_id IS UNIQUE",
            "CREATE CONSTRAINT feedback_id_unique IF NOT EXISTS FOR (fb:FeedbackRecord) REQUIRE fb.feedback_id IS UNIQUE",
            "CREATE CONSTRAINT knowledge_gap_id_unique IF NOT EXISTS FOR (kg:KnowledgeGap) REQUIRE kg.gap_id IS UNIQUE",
            "CREATE CONSTRAINT research_question_id_unique IF NOT EXISTS FOR (rqg:ResearchQuestion) REQUIRE rqg.rq_id IS UNIQUE",
            "CREATE CONSTRAINT knowledge_gap_seed_id_unique IF NOT EXISTS FOR (gs:KnowledgeGapSeed) REQUIRE gs.seed_id IS UNIQUE",
            "CREATE INDEX entity_name IF NOT EXISTS FOR (ke:KnowledgeEntity) ON (ke.name)",
            "CREATE INDEX entity_type IF NOT EXISTS FOR (ke:KnowledgeEntity) ON (ke.entity_type)",
            "CREATE INDEX global_community_version IF NOT EXISTS FOR (gc:GlobalCommunity) ON (gc.version)",
            "CREATE INDEX global_keyword_text IF NOT EXISTS FOR (gk:GlobalKeyword) ON (gk.keyword)",
            "CREATE INDEX rq_status IF NOT EXISTS FOR (rq:ResearchQuestionCandidate) ON (rq.status)",
            "CREATE INDEX rq_quality_score IF NOT EXISTS FOR (rq:ResearchQuestionCandidate) ON (rq.quality_score)",
            "CREATE INDEX feedback_candidate_id IF NOT EXISTS FOR (fb:FeedbackRecord) ON (fb.candidate_id)",
            "CREATE INDEX knowledge_gap_domain IF NOT EXISTS FOR (kg:KnowledgeGap) ON (kg.domain)",
            "CREATE INDEX knowledge_gap_type IF NOT EXISTS FOR (kg:KnowledgeGap) ON (kg.gap_type)",
            "CREATE INDEX research_question_domain IF NOT EXISTS FOR (rqg:ResearchQuestion) ON (rqg.domain)",
            "CREATE INDEX research_question_status IF NOT EXISTS FOR (rqg:ResearchQuestion) ON (rqg.status)",
            "CREATE INDEX research_question_quality IF NOT EXISTS FOR (rqg:ResearchQuestion) ON (rqg.quality_score)",
            "CREATE INDEX knowledge_gap_seed_kinds IF NOT EXISTS FOR (gs:KnowledgeGapSeed) ON (gs.gap_kinds)",
        ]
        with self._driver.session() as session:
            for s in stmts:
                session.run(s)

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

        # Persist gap seeds from claim kinds for downstream scientific-question discovery.
        gap_seed_claims = []
        for c in claims or []:
            kinds = [str(x).strip() for x in (c.get("kinds") or []) if str(x).strip()]
            seed_kinds = [k for k in kinds if k in {"Gap", "FutureWork", "Limitation", "Critique"}]
            if not seed_kinds:
                continue
            claim_id = str(c.get("claim_id") or "").strip()
            if not claim_id:
                continue
            claim_key = str(c.get("claim_key") or claim_id).strip() or claim_id
            seed_id = f"{paper_id}:{claim_key}"
            gap_seed_claims.append(
                {
                    "seed_id": seed_id,
                    "claim_id": claim_id,
                    "claim_key": claim_key,
                    "claim_text": str(c.get("text") or ""),
                    "step_type": str(c.get("step_type") or ""),
                    "gap_kinds": seed_kinds,
                    "confidence": float(c.get("confidence") or 0.0),
                }
            )
        if not gap_seed_claims:
            return

        cypher_seed = """
MATCH (p:Paper {paper_id:$paper_id})
UNWIND $items AS it
MATCH (cl:Claim {claim_id: it.claim_id})
MERGE (gs:KnowledgeGapSeed {seed_id: it.seed_id})
ON CREATE SET gs.created_at = $now
SET gs.paper_id = $paper_id,
    gs.claim_id = it.claim_id,
    gs.claim_key = it.claim_key,
    gs.claim_text = it.claim_text,
    gs.step_type = it.step_type,
    gs.gap_kinds = it.gap_kinds,
    gs.confidence = it.confidence,
    gs.updated_at = $now
MERGE (p)-[:HAS_GAP_SEED]->(gs)
MERGE (cl)-[:INDICATES_GAP]->(gs)
"""
        with self._driver.session() as session:
            session.run(
                cypher_seed,
                paper_id=paper_id,
                items=gap_seed_claims,
                now=datetime.now(tz=timezone.utc).isoformat(),
            )

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

    def list_paper_ids_for_propositions(self, proposition_ids: list[str], limit: int = 200) -> list[str]:
        ids = [str(x).strip() for x in (proposition_ids or []) if str(x).strip()]
        if not ids:
            return []
        limit = max(1, min(5000, int(limit)))
        cypher = """
MATCH (p:Paper)-[:HAS_CLAIM]->(:Claim)-[:MAPS_TO]->(pr:Proposition)
WHERE pr.prop_id IN $prop_ids
RETURN DISTINCT p.paper_id AS paper_id
LIMIT $limit
"""
        with self._driver.session() as session:
            rows = session.run(cypher, prop_ids=ids, limit=limit)
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
       c.purpose_labels AS purpose_labels,
       c.purpose_scores AS purpose_scores
ORDER BY c.total_mentions DESC
LIMIT 200
""",
                    paper_id=paper_id,
                )
            ]

            # Overlay cite purpose edits
            outgoing: list[dict] = []
            for o in outgoing_raw:
                cited_id = str(o.get("cited_paper_id") or "")
                machine_labels = list(o.get("purpose_labels") or [])
                machine_scores = list(o.get("purpose_scores") or [])
                human = human_cites.get(cited_id) if isinstance(human_cites, dict) else None
                cleared = cited_id in cites_cleared
                if cleared:
                    labels = []
                    scores = []
                    source = "cleared"
                    human_labels = None
                    human_scores = None
                elif isinstance(human, dict) and human.get("labels") is not None:
                    labels = list(human.get("labels") or [])
                    scores = list(human.get("scores") or [])
                    source = "human"
                    human_labels = labels
                    human_scores = scores
                else:
                    labels = machine_labels
                    scores = machine_scores
                    source = "machine"
                    human_labels = None
                    human_scores = None
                out = dict(o)
                out["purpose_labels_machine"] = machine_labels
                out["purpose_scores_machine"] = machine_scores
                out["purpose_labels_human"] = human_labels
                out["purpose_scores_human"] = human_scores
                out["purpose_source"] = source
                out["purpose_labels"] = labels
                out["purpose_scores"] = scores
                if needs_review and source in {"human", "cleared"}:
                    out["pending_machine_purpose_labels"] = machine_labels
                    out["pending_machine_purpose_scores"] = machine_scores
                outgoing.append(out)

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
            # Clean up orphaned Propositions (those with no incoming MAPS_TO relationships)
            # This is safe because Propositions are only accessed via Claims
            """
MATCH (pr:Proposition)
WHERE NOT EXISTS((pr)<-[:MAPS_TO]-())
DETACH DELETE pr
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

    def list_proposition_similarity_rows(self, paper_id: str | None = None, limit: int = 200000) -> list[dict]:
        """
        Return proposition texts with claim/textbook provenance for similarity indexing.

        Notes:
        - Prefers claim provenance when a proposition is linked to both a claim and a textbook entity.
        - Deduplicates by proposition id so callers get a stable single row per proposition.
        """
        pid = (paper_id or "").strip()
        limit = max(1, min(200000, int(limit)))
        cypher = """
MATCH (pr:Proposition)
OPTIONAL MATCH (cl:Claim)-[:MAPS_TO]->(pr)
OPTIONAL MATCH (p:Paper)-[:HAS_CLAIM]->(cl)
WHERE ($paper_id = '' OR p.paper_id = $paper_id)
OPTIONAL MATCH (ke:KnowledgeEntity)-[:MAPS_TO]->(pr)
OPTIONAL MATCH (tc:TextbookChapter)-[:HAS_ENTITY]->(ke)
OPTIONAL MATCH (tb:Textbook)-[:HAS_CHAPTER]->(tc)
RETURN pr.prop_id AS node_id,
       coalesce(p.paper_id, '') AS paper_id,
       coalesce(p.paper_source, '') AS paper_source,
       coalesce(pr.canonical_text, '') AS text,
       CASE
         WHEN cl IS NOT NULL THEN 'claim'
         WHEN ke IS NOT NULL THEN 'textbook_entity'
         ELSE 'proposition'
       END AS source_kind,
       coalesce(cl.claim_id, ke.entity_id, pr.prop_id) AS source_id,
       tb.textbook_id AS textbook_id,
       tc.chapter_id AS chapter_id
LIMIT $limit
"""
        with self._driver.session() as session:
            rows = [dict(r) for r in session.run(cypher, paper_id=pid, limit=limit)]

        priority = {"claim": 3, "textbook_entity": 2, "proposition": 1}
        merged: dict[str, dict] = {}
        for row in rows:
            node_id = str(row.get("node_id") or "").strip()
            text = str(row.get("text") or "").strip()
            if not node_id or not text:
                continue
            normalized = {
                "node_id": node_id,
                "paper_id": str(row.get("paper_id") or "").strip(),
                "paper_source": str(row.get("paper_source") or "").strip(),
                "text": text,
                "source_kind": str(row.get("source_kind") or "proposition").strip() or "proposition",
                "source_id": str(row.get("source_id") or node_id).strip() or node_id,
                "textbook_id": str(row.get("textbook_id") or "").strip() or None,
                "chapter_id": str(row.get("chapter_id") or "").strip() or None,
            }
            existing = merged.get(node_id)
            if not existing:
                merged[node_id] = normalized
                continue
            if priority.get(normalized["source_kind"], 0) > priority.get(existing.get("source_kind", ""), 0):
                existing["source_kind"] = normalized["source_kind"]
                existing["source_id"] = normalized["source_id"]
            for key in ("paper_id", "paper_source", "textbook_id", "chapter_id"):
                if not existing.get(key) and normalized.get(key):
                    existing[key] = normalized[key]
        return list(merged.values())[:limit]

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
OPTIONAL MATCH (cl)-[:MAPS_TO]->(pr:Proposition)
RETURN 'claim' AS kind,
       cl.claim_id AS source_id,
       p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       cl.step_type AS step_type,
       cl.text AS text,
       cl.confidence AS confidence,
       pr.prop_id AS proposition_id,
       [ch IN chunks WHERE ch.chunk_id IS NOT NULL | ch.chunk_id] AS evidence_chunk_ids,
       coalesce(cl.evidence_quote, head([ch IN chunks WHERE trim(coalesce(ch.text, '')) <> '' | ch.text]), '') AS evidence_quote
ORDER BY p.paper_id ASC, cl.claim_id ASC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, paper_id=pid, limit=limit)]

    def list_proposition_structured_rows(self, paper_id: str | None = None, limit: int = 50000) -> list[dict]:
        pid = (paper_id or "").strip()
        limit = max(1, min(200000, int(limit)))
        cypher = """
MATCH (pr:Proposition)
OPTIONAL MATCH (cl:Claim)-[:MAPS_TO]->(pr)
OPTIONAL MATCH (p:Paper)-[:HAS_CLAIM]->(cl)
WHERE ($paper_id = '' OR p.paper_id = $paper_id)
OPTIONAL MATCH (ke:KnowledgeEntity)-[:MAPS_TO]->(pr)
OPTIONAL MATCH (tc:TextbookChapter)-[:HAS_ENTITY]->(ke)
OPTIONAL MATCH (tb:Textbook)-[:HAS_CHAPTER]->(tc)
OPTIONAL MATCH (ev:EvidenceEvent)-[:TO_PROPOSITION]->(pr)
RETURN 'proposition' AS kind,
       pr.prop_id AS source_id,
       pr.prop_id AS proposition_id,
       p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       pr.canonical_text AS text,
       CASE
         WHEN cl IS NOT NULL THEN 'claim'
         WHEN ke IS NOT NULL THEN 'textbook_entity'
         ELSE 'proposition'
       END AS source_kind,
       coalesce(cl.claim_id, ke.entity_id, pr.prop_id) AS source_ref_id,
       tb.textbook_id AS textbook_id,
       tc.chapter_id AS chapter_id,
       coalesce(cl.evidence_quote, ke.description, pr.canonical_text) AS evidence_quote,
       ev.event_id AS evidence_event_id,
       ev.event_type AS evidence_event_type
LIMIT $limit
"""
        with self._driver.session() as session:
            rows = [dict(r) for r in session.run(cypher, paper_id=pid, limit=limit)]

        merged: dict[str, dict] = {}
        priority = {"claim": 3, "textbook_entity": 2, "proposition": 1}
        for row in rows:
            source_id = str(row.get("source_id") or "").strip()
            text = str(row.get("text") or "").strip()
            if not source_id or not text:
                continue
            current = {
                "kind": "proposition",
                "source_id": source_id,
                "proposition_id": str(row.get("proposition_id") or source_id).strip() or source_id,
                "paper_id": str(row.get("paper_id") or "").strip() or None,
                "paper_source": str(row.get("paper_source") or "").strip() or None,
                "text": text,
                "source_kind": str(row.get("source_kind") or "proposition").strip() or "proposition",
                "source_ref_id": str(row.get("source_ref_id") or source_id).strip() or source_id,
                "textbook_id": str(row.get("textbook_id") or "").strip() or None,
                "chapter_id": str(row.get("chapter_id") or "").strip() or None,
                "evidence_quote": str(row.get("evidence_quote") or "").strip() or None,
                "evidence_event_id": str(row.get("evidence_event_id") or "").strip() or None,
                "evidence_event_type": str(row.get("evidence_event_type") or "").strip() or None,
            }
            existing = merged.get(source_id)
            if not existing:
                merged[source_id] = current
                continue
            if priority.get(current["source_kind"], 0) > priority.get(existing.get("source_kind", ""), 0):
                existing["source_kind"] = current["source_kind"]
                existing["source_ref_id"] = current["source_ref_id"]
                if current.get("evidence_quote"):
                    existing["evidence_quote"] = current["evidence_quote"]
            for key in ("paper_id", "paper_source", "textbook_id", "chapter_id", "evidence_event_id", "evidence_event_type"):
                if not existing.get(key) and current.get(key):
                    existing[key] = current[key]
        return list(merged.values())[:limit]

    def get_grounding_rows_for_structured_ids(self, ids: list[dict], limit: int = 200) -> list[dict]:
        limit = max(1, min(500, int(limit)))
        claim_ids: list[str] = []
        logic_ids: list[str] = []
        proposition_ids: list[str] = []
        for item in ids or []:
            kind = str(item.get("kind") or item.get("source_kind") or "").strip().lower()
            ident = str(item.get("id") or item.get("source_id") or "").strip()
            if not ident:
                continue
            if kind == "claim":
                claim_ids.append(ident)
            elif kind in {"logic_step", "logic"}:
                logic_ids.append(ident)
            elif kind == "proposition":
                proposition_ids.append(ident)

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

            if proposition_ids and len(rows) < limit:
                proposition_cypher = """
UNWIND $proposition_ids AS prop_id
MATCH (pr:Proposition {prop_id: prop_id})
OPTIONAL MATCH (cl:Claim)-[:MAPS_TO]->(pr)
OPTIONAL MATCH (cl)-[:EVIDENCED_BY]->(ch:Chunk)
OPTIONAL MATCH (ke:KnowledgeEntity)-[:MAPS_TO]->(pr)
OPTIONAL MATCH (tc:TextbookChapter)-[:HAS_ENTITY]->(ke)
OPTIONAL MATCH (tb:Textbook)-[:HAS_CHAPTER]->(tc)
OPTIONAL MATCH (ev:EvidenceEvent)-[:TO_PROPOSITION]->(pr)
RETURN 'proposition' AS source_kind,
       pr.prop_id AS source_id,
       coalesce(cl.evidence_quote, ch.text, ke.description, pr.canonical_text) AS quote,
       ch.chunk_id AS chunk_id,
       ch.md_path AS md_path,
       ch.start_line AS start_line,
       ch.end_line AS end_line,
       tb.textbook_id AS textbook_id,
       tc.chapter_id AS chapter_id,
       ev.event_id AS evidence_event_id,
       ev.event_type AS evidence_event_type
LIMIT $limit
"""
                rows.extend(
                    dict(r)
                    for r in session.run(
                        proposition_cypher,
                        proposition_ids=proposition_ids[: max(1, limit - len(rows))],
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

    def list_claim_rows_for_evolution(self, paper_id: str | None = None, limit: int = 500000) -> list[dict]:
        pid = (paper_id or "").strip()
        limit = max(1, min(500000, int(limit)))
        cypher = """
MATCH (p:Paper)-[:HAS_CLAIM]->(cl:Claim)
WHERE ($paper_id = '' OR p.paper_id = $paper_id)
RETURN p.paper_id AS paper_id,
       p.year AS paper_year,
       cl.claim_id AS claim_id,
       cl.claim_key AS claim_key,
       cl.text AS text,
       cl.step_type AS step_type,
       cl.kinds AS kinds,
       cl.confidence AS confidence
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, paper_id=pid, limit=limit)]

    def upsert_proposition_mentions_for_claims(self, paper_id: str, claims: list[dict], paper_year: int | None = None) -> dict[str, int]:
        pid = str(paper_id or "").strip()
        if not pid:
            return {"claims": 0, "propositions": 0}
        items: list[dict] = []
        for c in claims or []:
            claim_id = str(c.get("claim_id") or "").strip()
            text = str(c.get("text") or "").strip()
            if not claim_id or not text:
                continue
            step_type = str(c.get("step_type") or "").strip()
            kinds = [str(x).strip() for x in (c.get("kinds") or []) if str(x).strip()]
            prop_key = proposition_key_for_claim(text=text, step_type=step_type, kinds=kinds)
            prop_id = proposition_id_for_key(prop_key)
            try:
                confidence = float(c.get("confidence") or 0.5)
            except Exception:
                confidence = 0.5
            confidence = max(0.0, min(1.0, confidence))
            event_id = hashlib.sha256((f"mention\0{pid}\0{claim_id}").encode("utf-8", errors="ignore")).hexdigest()[:32]
            items.append(
                {
                    "paper_id": pid,
                    "claim_id": claim_id,
                    "prop_id": prop_id,
                    "prop_key": prop_key,
                    "canonical_text": normalize_proposition_text(text),
                    "step_type": step_type,
                    "kinds": kinds,
                    "confidence": confidence,
                    "strength": confidence,
                    "event_id": event_id,
                    "event_time": iso_time_for_paper_year(paper_year),
                }
            )

        if not items:
            return {"claims": 0, "propositions": 0}

        cypher = """
UNWIND $items AS it
MATCH (p:Paper {paper_id: it.paper_id})-[:HAS_CLAIM]->(cl:Claim {claim_id: it.claim_id})
MERGE (pr:Proposition {prop_id: it.prop_id})
ON CREATE SET pr.prop_key = it.prop_key,
              pr.canonical_text = it.canonical_text,
              pr.created_at = $now
SET pr.last_seen_at = $now,
    pr.step_types_seen = CASE
        WHEN it.step_type = '' THEN coalesce(pr.step_types_seen, [])
        WHEN it.step_type IN coalesce(pr.step_types_seen, []) THEN pr.step_types_seen
        ELSE coalesce(pr.step_types_seen, []) + [it.step_type]
    END,
    pr.kinds_seen = reduce(acc = coalesce(pr.kinds_seen, []), k IN it.kinds |
        CASE WHEN k IN acc THEN acc ELSE acc + [k] END)
MERGE (cl)-[:MAPS_TO]->(pr)
MERGE (ev:EvidenceEvent {event_id: it.event_id})
ON CREATE SET ev.origin = 'mention',
              ev.created_at = $now
SET ev.event_type = 'SUPPORTS',
    ev.status = 'accepted',
    ev.paper_id = it.paper_id,
    ev.claim_id = it.claim_id,
    ev.source_prop_id = it.prop_id,
    ev.target_prop_id = it.prop_id,
    ev.confidence = it.confidence,
    ev.strength = it.strength,
    ev.event_time = it.event_time
MERGE (cl)-[:TRIGGERS_EVENT]->(ev)
MERGE (ev)-[:ABOUT]->(pr)
MERGE (ev)-[:FROM_PROPOSITION]->(pr)
MERGE (ev)-[:TO_PROPOSITION]->(pr)
"""
        with self._driver.session() as session:
            session.run(cypher, items=items, now=datetime.now(tz=timezone.utc).isoformat())
        return {"claims": len(items), "propositions": len({str(it["prop_id"]) for it in items})}

    def list_proposition_candidate_pairs(self, min_score: float = 0.9, limit: int = 50000) -> list[dict]:
        limit = max(1, min(500000, int(limit)))
        cypher = """
MATCH (a:Claim)-[s:SIMILAR_CLAIM]->(b:Claim)
WHERE a.paper_id <> b.paper_id
  AND coalesce(s.score, 0.0) >= $min_score
MATCH (a)-[:MAPS_TO]->(pa:Proposition)
MATCH (b)-[:MAPS_TO]->(pb:Proposition)
WHERE pa.prop_id <> pb.prop_id
OPTIONAL MATCH (sp:Paper {paper_id: a.paper_id})
OPTIONAL MATCH (tp:Paper {paper_id: b.paper_id})
OPTIONAL MATCH (sp)-[c:CITES]->(tp)
RETURN a.claim_id AS source_claim_id,
       b.claim_id AS target_claim_id,
       a.paper_id AS source_paper_id,
       coalesce(toLower(s.mode), 'embedding') AS similarity_mode,
       b.paper_id AS target_paper_id,
       a.text AS source_text,
       b.text AS target_text,
       coalesce(a.confidence, 0.5) AS source_confidence,
       coalesce(b.confidence, 0.5) AS target_confidence,
       coalesce(c.purpose_labels, []) AS citation_purpose_labels,
       coalesce(c.purpose_scores, []) AS citation_purpose_scores,
       coalesce(s.score, 0.0) AS similarity,
       pa.prop_id AS source_prop_id,
       pb.prop_id AS target_prop_id
ORDER BY similarity DESC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, min_score=float(min_score), limit=limit)]

    def replace_inferred_relation_events(self, items: list[dict], built_at: str) -> None:
        clear_cypher = """
MATCH (e:EvidenceEvent {origin:'inferred_relation'})
DETACH DELETE e
"""
        upsert_cypher = """
UNWIND $items AS it
MATCH (sp:Proposition {prop_id: it.source_prop_id})
MATCH (tp:Proposition {prop_id: it.target_prop_id})
OPTIONAL MATCH (sc:Claim {claim_id: it.source_claim_id})
OPTIONAL MATCH (tc:Claim {claim_id: it.target_claim_id})
MERGE (e:EvidenceEvent {event_id: it.event_id})
ON CREATE SET e.origin = 'inferred_relation',
              e.created_at = $built_at
SET e.event_type = it.event_type,
    e.status = it.status,
    e.confidence = it.confidence,
    e.strength = it.strength,
    e.source_prop_id = it.source_prop_id,
    e.target_prop_id = it.target_prop_id,
    e.paper_id = it.target_paper_id,
    e.claim_id = it.target_claim_id,
    e.raw_similarity = coalesce(it.raw_similarity, 0.0),
    e.inference_version = coalesce(it.inference_version, 'v1'),
    e.event_time = it.event_time
MERGE (e)-[:FROM_PROPOSITION]->(sp)
MERGE (e)-[:TO_PROPOSITION]->(tp)
MERGE (e)-[:ABOUT]->(tp)
FOREACH (_ IN CASE WHEN sc IS NULL THEN [] ELSE [1] END | MERGE (sc)-[:TRIGGERS_EVENT]->(e))
FOREACH (_ IN CASE WHEN tc IS NULL THEN [] ELSE [1] END | MERGE (tc)-[:TRIGGERS_EVENT]->(e))
"""
        with self._driver.session() as session:
            session.run(clear_cypher)
            batch = list(items or [])
            for i in range(0, len(batch), 200):
                session.run(upsert_cypher, items=batch[i : i + 200], built_at=str(built_at))

    def _replace_proposition_relation_edges(self, rel_type: str, items: list[dict], built_at: str) -> None:
        kind = str(rel_type or "").strip().upper()
        if kind not in {"SUPPORTS", "CHALLENGES", "SUPERSEDES"}:
            raise ValueError(f"Unsupported relation type: {rel_type}")
        clear_cypher = f"""
MATCH (:Proposition)-[r:{kind}]->(:Proposition)
DELETE r
"""
        upsert_cypher = f"""
UNWIND $items AS it
MATCH (a:Proposition {{prop_id: it.source_prop_id}})
MATCH (b:Proposition {{prop_id: it.target_prop_id}})
MERGE (a)-[r:{kind}]->(b)
SET r.score = it.score,
    r.evidence_count = it.evidence_count,
    r.updated_at = $built_at,
    r.origin = 'inferred_relation'
"""
        with self._driver.session() as session:
            session.run(clear_cypher)
            batch = list(items or [])
            for i in range(0, len(batch), 200):
                session.run(upsert_cypher, items=batch[i : i + 200], built_at=str(built_at))

    def replace_proposition_support_edges(self, items: list[dict], built_at: str) -> None:
        self._replace_proposition_relation_edges("SUPPORTS", items, built_at)

    def replace_proposition_challenge_edges(self, items: list[dict], built_at: str) -> None:
        self._replace_proposition_relation_edges("CHALLENGES", items, built_at)

    def replace_proposition_supersede_edges(self, items: list[dict], built_at: str) -> None:
        self._replace_proposition_relation_edges("SUPERSEDES", items, built_at)

    def recompute_proposition_states(self) -> dict[str, int]:
        update_cypher = """
MATCH (pr:Proposition)
OPTIONAL MATCH (e:EvidenceEvent)-[:TO_PROPOSITION]->(pr)
WHERE coalesce(e.status, '') = 'accepted'
WITH pr,
     sum(CASE WHEN e.event_type = 'SUPPORTS' THEN coalesce(e.strength, e.confidence, 0.5) ELSE 0.0 END) AS support_w,
     sum(CASE WHEN e.event_type = 'CHALLENGES' THEN coalesce(e.strength, e.confidence, 0.5) ELSE 0.0 END) AS challenge_w,
     sum(CASE WHEN e.event_type = 'SUPERSEDES' THEN coalesce(e.strength, e.confidence, 0.5) ELSE 0.0 END) AS supersede_w
WITH pr, support_w, challenge_w, supersede_w, (support_w + challenge_w + supersede_w) AS total_w
WITH pr,
     CASE WHEN total_w <= 0 THEN 0.55 ELSE support_w / total_w END AS support_ratio,
     CASE WHEN total_w <= 0 THEN 0.00 ELSE challenge_w / total_w END AS challenge_ratio,
     CASE WHEN total_w <= 0 THEN 0.00 ELSE supersede_w / total_w END AS supersede_ratio
WITH pr, (0.55 + 0.45 * support_ratio - 0.45 * challenge_ratio - 0.65 * supersede_ratio) AS raw_score
WITH pr, CASE
    WHEN raw_score < 0 THEN 0.0
    WHEN raw_score > 1 THEN 1.0
    ELSE raw_score
END AS final_score
SET pr.current_score = final_score,
pr.current_state = CASE
    WHEN final_score >= 0.70 THEN 'stable'
    WHEN final_score >= 0.40 THEN 'challenged'
    ELSE 'superseded'
END,
pr.score_updated_at = $now
"""
        stats_cypher = """
MATCH (pr:Proposition)
RETURN count(pr) AS total,
       sum(CASE WHEN pr.current_state = 'stable' THEN 1 ELSE 0 END) AS stable,
       sum(CASE WHEN pr.current_state = 'challenged' THEN 1 ELSE 0 END) AS challenged,
       sum(CASE WHEN pr.current_state = 'superseded' THEN 1 ELSE 0 END) AS superseded
"""
        with self._driver.session() as session:
            now = datetime.now(tz=timezone.utc).isoformat()
            session.run(update_cypher, now=now)
            row = session.run(stats_cypher).single()
            if not row:
                return {"total": 0, "stable": 0, "challenged": 0, "superseded": 0}
            return {
                "total": int(row.get("total") or 0),
                "stable": int(row.get("stable") or 0),
                "challenged": int(row.get("challenged") or 0),
                "superseded": int(row.get("superseded") or 0),
            }

    def list_propositions(self, limit: int = 100, state: str | None = None, query: str | None = None) -> list[dict]:
        limit = max(1, min(1000, int(limit)))
        st = str(state or "").strip().lower()
        q = str(query or "").strip()
        cypher = """
MATCH (pr:Proposition)
WHERE ($state = '' OR toLower(coalesce(pr.current_state, '')) = $state)
  AND ($search_q = '' OR toLower(coalesce(pr.canonical_text, '')) CONTAINS toLower($search_q))
OPTIONAL MATCH (cl:Claim)-[:MAPS_TO]->(pr)
OPTIONAL MATCH (e:EvidenceEvent)-[:TO_PROPOSITION]->(pr)
WHERE coalesce(e.status, '') = 'accepted'
RETURN pr.prop_id AS prop_id,
       pr.prop_key AS prop_key,
       pr.canonical_text AS canonical_text,
       pr.current_state AS current_state,
       pr.current_score AS current_score,
       pr.score_updated_at AS score_updated_at,
       count(DISTINCT cl) AS mention_count,
       sum(CASE WHEN e.event_type = 'SUPPORTS' THEN 1 ELSE 0 END) AS supports,
       sum(CASE WHEN e.event_type = 'CHALLENGES' THEN 1 ELSE 0 END) AS challenges,
       sum(CASE WHEN e.event_type = 'SUPERSEDES' THEN 1 ELSE 0 END) AS supersedes
ORDER BY coalesce(pr.current_score, 0.0) DESC, mention_count DESC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, state=st, search_q=q, limit=limit)]

    def list_conflict_hotspots(self, limit: int = 50, min_events: int = 1) -> list[dict]:
        limit = max(1, min(1000, int(limit)))
        min_events = max(1, min(1000, int(min_events)))
        cypher = """
MATCH (pr:Proposition)
OPTIONAL MATCH (e:EvidenceEvent)-[:TO_PROPOSITION]->(pr)
WHERE coalesce(e.status, '') = 'accepted'
WITH pr,
     sum(CASE WHEN e.event_type = 'CHALLENGES' THEN 1 ELSE 0 END) AS challenge_events,
     sum(CASE WHEN e.event_type = 'SUPERSEDES' THEN 1 ELSE 0 END) AS supersede_events,
     count(DISTINCT CASE WHEN e.event_type IN ['CHALLENGES','SUPERSEDES'] THEN e.paper_id ELSE NULL END) AS source_paper_count
WITH pr, challenge_events, supersede_events, source_paper_count, (challenge_events + supersede_events) AS conflict_events
WHERE conflict_events >= $min_events
RETURN pr.prop_id AS prop_id,
       pr.canonical_text AS canonical_text,
       pr.current_state AS current_state,
       pr.current_score AS current_score,
       challenge_events,
       supersede_events,
       conflict_events,
       source_paper_count
ORDER BY conflict_events DESC, supersede_events DESC, challenge_events DESC, coalesce(pr.current_score, 1.0) ASC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, limit=limit, min_events=min_events)]

    def list_gap_like_claims(self, limit: int = 200, kinds: list[str] | None = None) -> list[dict]:
        limit = max(1, min(5000, int(limit)))
        use_kinds = [str(k).strip() for k in (kinds or ["Gap", "FutureWork", "Limitation", "Critique"]) if str(k).strip()]
        if not use_kinds:
            return []

        cypher = """
MATCH (p:Paper)-[:HAS_CLAIM]->(cl:Claim)
WHERE any(k IN coalesce(cl.kinds, []) WHERE k IN $kinds)
OPTIONAL MATCH (cl)-[:MAPS_TO]->(pr:Proposition)
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
       pr.prop_id AS prop_id,
       pr.canonical_text AS prop_text,
       count(DISTINCT ev) AS evidence_count
ORDER BY confidence DESC, evidence_count DESC, cl.claim_id ASC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, kinds=use_kinds, limit=limit)]

    def list_gap_seeds(self, limit: int = 300, kinds: list[str] | None = None) -> list[dict]:
        limit = max(1, min(5000, int(limit)))
        use_kinds = [str(k).strip() for k in (kinds or ["Gap", "FutureWork", "Limitation", "Critique"]) if str(k).strip()]
        if not use_kinds:
            return []

        cypher = """
MATCH (gs:KnowledgeGapSeed)
WHERE any(k IN coalesce(gs.gap_kinds, []) WHERE k IN $kinds)
OPTIONAL MATCH (cl:Claim {claim_id: gs.claim_id})<-[:HAS_CLAIM]-(p:Paper)
OPTIONAL MATCH (cl)-[:MAPS_TO]->(pr:Proposition)
RETURN gs.seed_id AS seed_id,
       gs.claim_id AS claim_id,
       gs.claim_key AS claim_key,
       gs.claim_text AS text,
       gs.step_type AS step_type,
       coalesce(gs.gap_kinds, []) AS kinds,
       coalesce(gs.confidence, 0.0) AS confidence,
       p.paper_id AS paper_id,
       p.paper_source AS paper_source,
       p.title AS paper_title,
       p.year AS paper_year,
       pr.prop_id AS prop_id,
       pr.canonical_text AS prop_text
ORDER BY confidence DESC, gs.updated_at DESC, gs.seed_id ASC
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, kinds=use_kinds, limit=limit)]

    def upsert_discovery_graph(
        self,
        *,
        domain: str,
        batch_id: str,
        gaps: list[dict],
        questions: list[dict],
        built_at: str,
    ) -> None:
        domain_norm = str(domain or "").strip().lower()
        bid = str(batch_id or "").strip()
        ts = str(built_at or datetime.now(tz=timezone.utc).isoformat())
        if not bid:
            return

        gap_items: list[dict] = []
        for g in gaps or []:
            gap_id = str(g.get("gap_id") or "").strip()
            if not gap_id:
                continue
            gap_items.append(
                {
                    "gap_id": gap_id,
                    "gap_type": str(g.get("gap_type") or "seed"),
                    "title": str(g.get("title") or ""),
                    "description": str(g.get("description") or ""),
                    "missing_evidence_statement": str(g.get("missing_evidence_statement") or ""),
                    "priority_score": float(g.get("priority_score") or 0.0),
                    "signals_json": json.dumps(g.get("signals") or {}, ensure_ascii=False),
                    "source_claim_ids": [str(x).strip() for x in (g.get("source_claim_ids") or []) if str(x).strip()],
                    "source_prop_ids": [str(x).strip() for x in (g.get("source_proposition_ids") or []) if str(x).strip()],
                    "source_paper_ids": [str(x).strip() for x in (g.get("source_paper_ids") or []) if str(x).strip()],
                }
            )

        if gap_items:
            cypher_gaps = """
UNWIND $items AS g
MERGE (kg:KnowledgeGap {gap_id: g.gap_id})
ON CREATE SET kg.created_at = $built_at
SET kg.domain = $domain,
    kg.batch_id = $batch_id,
    kg.gap_type = g.gap_type,
    kg.title = g.title,
    kg.description = g.description,
    kg.missing_evidence_statement = g.missing_evidence_statement,
    kg.priority_score = g.priority_score,
    kg.signals_json = g.signals_json,
    kg.updated_at = $built_at
WITH kg, g
UNWIND coalesce(g.source_claim_ids, []) AS cid
MATCH (cl:Claim {claim_id: cid})
MERGE (kg)-[:GAP_FROM_CLAIM]->(cl)
"""
            cypher_gap_props = """
UNWIND $items AS g
MATCH (kg:KnowledgeGap {gap_id: g.gap_id})
UNWIND coalesce(g.source_prop_ids, []) AS pid
MATCH (pr:Proposition {prop_id: pid})
MERGE (kg)-[:GAP_FROM_PROPOSITION]->(pr)
"""
            cypher_gap_papers = """
UNWIND $items AS g
MATCH (kg:KnowledgeGap {gap_id: g.gap_id})
UNWIND coalesce(g.source_paper_ids, []) AS pid
MATCH (p:Paper {paper_id: pid})
MERGE (kg)-[:GAP_FROM_PAPER]->(p)
"""
            with self._driver.session() as session:
                session.run(
                    cypher_gaps,
                    items=gap_items,
                    domain=domain_norm,
                    batch_id=bid,
                    built_at=ts,
                )
                session.run(cypher_gap_props, items=gap_items)
                session.run(cypher_gap_papers, items=gap_items)

        question_items: list[dict] = []
        for q in questions or []:
            rq_id = str(q.get("candidate_id") or q.get("rq_id") or "").strip()
            question = str(q.get("question") or "").strip()
            if not rq_id or not question:
                continue
            support = _split_prefixed_evidence_ids([str(x) for x in (q.get("support_evidence_ids") or [])])
            challenge = _split_prefixed_evidence_ids([str(x) for x in (q.get("challenge_evidence_ids") or [])])
            question_items.append(
                {
                    "rq_id": rq_id,
                    "gap_id": str(q.get("gap_id") or ""),
                    "gap_type": str(q.get("gap_type") or "seed"),
                    "question": question,
                    "motivation": str(q.get("motivation") or ""),
                    "novelty": str(q.get("novelty") or ""),
                    "proposed_method": str(q.get("proposed_method") or ""),
                    "difference": str(q.get("difference") or ""),
                    "feasibility": str(q.get("feasibility") or ""),
                    "risk_statement": str(q.get("risk_statement") or ""),
                    "timeline": str(q.get("timeline") or ""),
                    "evaluation_metrics": [str(x).strip() for x in (q.get("evaluation_metrics") or []) if str(x).strip()],
                    "generation_mode": str(q.get("generation_mode") or "template"),
                    "prompt_variant": str(q.get("prompt_variant") or ""),
                    "generation_confidence": float(q.get("generation_confidence") or 0.0),
                    "optimization_score": float(q.get("optimization_score") or 0.0),
                    "novelty_score": float(q.get("novelty_score") or 0.0),
                    "feasibility_score": float(q.get("feasibility_score") or 0.0),
                    "relevance_score": float(q.get("relevance_score") or 0.0),
                    "support_coverage": float(q.get("support_coverage") or 0.0),
                    "challenge_coverage": float(q.get("challenge_coverage") or 0.0),
                    "quality_score": float(q.get("quality_score") or 0.0),
                    "status": str(q.get("status") or "draft"),
                    "rank": int(q.get("rank") or 0),
                    "support_claim_ids": support["claim_ids"],
                    "support_prop_ids": support["prop_ids"],
                    "support_chunk_ids": support["chunk_ids"],
                    "support_event_ids": support["event_ids"],
                    "challenge_claim_ids": challenge["claim_ids"],
                    "challenge_prop_ids": challenge["prop_ids"],
                    "challenge_chunk_ids": challenge["chunk_ids"],
                    "challenge_event_ids": challenge["event_ids"],
                    "source_claim_ids": [str(x).strip() for x in (q.get("source_claim_ids") or []) if str(x).strip()],
                    "source_prop_ids": [str(x).strip() for x in (q.get("source_proposition_ids") or []) if str(x).strip()],
                    "source_paper_ids": [str(x).strip() for x in (q.get("source_paper_ids") or []) if str(x).strip()],
                    "inspiration_adjacent_paper_ids": [
                        str(x).strip() for x in (q.get("inspiration_adjacent_paper_ids") or []) if str(x).strip()
                    ],
                    "inspiration_random_paper_ids": [
                        str(x).strip() for x in (q.get("inspiration_random_paper_ids") or []) if str(x).strip()
                    ],
                    "inspiration_community_paper_ids": [
                        str(x).strip() for x in (q.get("inspiration_community_paper_ids") or []) if str(x).strip()
                    ],
                }
            )
        if not question_items:
            return

        cypher_rq = """
UNWIND $items AS q
MERGE (rq:ResearchQuestion {rq_id: q.rq_id})
ON CREATE SET rq.created_at = $built_at
SET rq.domain = $domain,
    rq.batch_id = $batch_id,
    rq.gap_id = q.gap_id,
    rq.gap_type = q.gap_type,
    rq.question = q.question,
    rq.motivation = q.motivation,
    rq.novelty = q.novelty,
    rq.proposed_method = q.proposed_method,
    rq.difference = q.difference,
    rq.feasibility = q.feasibility,
    rq.risk_statement = q.risk_statement,
    rq.timeline = q.timeline,
    rq.evaluation_metrics = q.evaluation_metrics,
    rq.generation_mode = q.generation_mode,
    rq.prompt_variant = q.prompt_variant,
    rq.generation_confidence = q.generation_confidence,
    rq.optimization_score = q.optimization_score,
    rq.novelty_score = q.novelty_score,
    rq.feasibility_score = q.feasibility_score,
    rq.relevance_score = q.relevance_score,
    rq.support_coverage = q.support_coverage,
    rq.challenge_coverage = q.challenge_coverage,
    rq.quality_score = q.quality_score,
    rq.status = q.status,
    rq.rank = q.rank,
    rq.updated_at = $built_at
WITH rq, q
FOREACH (_ IN CASE WHEN q.gap_id = '' THEN [] ELSE [1] END |
    MERGE (kg:KnowledgeGap {gap_id: q.gap_id})
    ON CREATE SET kg.created_at = $built_at, kg.domain = $domain, kg.batch_id = $batch_id
    MERGE (rq)-[:ADDRESSES_GAP]->(kg)
)
"""
        with self._driver.session() as session:
            session.run(
                cypher_rq,
                items=question_items,
                domain=domain_norm,
                batch_id=bid,
                built_at=ts,
            )

            for row in question_items:
                rid = row["rq_id"]
                # support edges
                if row["support_claim_ids"]:
                    session.run(
                        """
MATCH (rq:ResearchQuestion {rq_id:$rq_id})
UNWIND $ids AS id
MATCH (cl:Claim {claim_id:id})
MERGE (rq)-[:SUPPORTED_BY]->(cl)
""",
                        rq_id=rid,
                        ids=row["support_claim_ids"],
                    )
                if row["support_prop_ids"]:
                    session.run(
                        """
MATCH (rq:ResearchQuestion {rq_id:$rq_id})
UNWIND $ids AS id
MATCH (pr:Proposition {prop_id:id})
MERGE (rq)-[:SUPPORTED_BY]->(pr)
""",
                        rq_id=rid,
                        ids=row["support_prop_ids"],
                    )
                if row["support_chunk_ids"]:
                    session.run(
                        """
MATCH (rq:ResearchQuestion {rq_id:$rq_id})
UNWIND $ids AS id
MATCH (ch:Chunk {chunk_id:id})
MERGE (rq)-[:SUPPORTED_BY]->(ch)
""",
                        rq_id=rid,
                        ids=row["support_chunk_ids"],
                    )
                if row["support_event_ids"]:
                    session.run(
                        """
MATCH (rq:ResearchQuestion {rq_id:$rq_id})
UNWIND $ids AS id
MATCH (ev:EvidenceEvent {event_id:id})
MERGE (rq)-[:SUPPORTED_BY]->(ev)
""",
                        rq_id=rid,
                        ids=row["support_event_ids"],
                    )
                # challenge edges
                if row["challenge_claim_ids"]:
                    session.run(
                        """
MATCH (rq:ResearchQuestion {rq_id:$rq_id})
UNWIND $ids AS id
MATCH (cl:Claim {claim_id:id})
MERGE (rq)-[:CHALLENGED_BY]->(cl)
""",
                        rq_id=rid,
                        ids=row["challenge_claim_ids"],
                    )
                if row["challenge_prop_ids"]:
                    session.run(
                        """
MATCH (rq:ResearchQuestion {rq_id:$rq_id})
UNWIND $ids AS id
MATCH (pr:Proposition {prop_id:id})
MERGE (rq)-[:CHALLENGED_BY]->(pr)
""",
                        rq_id=rid,
                        ids=row["challenge_prop_ids"],
                    )
                if row["challenge_chunk_ids"]:
                    session.run(
                        """
MATCH (rq:ResearchQuestion {rq_id:$rq_id})
UNWIND $ids AS id
MATCH (ch:Chunk {chunk_id:id})
MERGE (rq)-[:CHALLENGED_BY]->(ch)
""",
                        rq_id=rid,
                        ids=row["challenge_chunk_ids"],
                    )
                if row["challenge_event_ids"]:
                    session.run(
                        """
MATCH (rq:ResearchQuestion {rq_id:$rq_id})
UNWIND $ids AS id
MATCH (ev:EvidenceEvent {event_id:id})
MERGE (rq)-[:CHALLENGED_BY]->(ev)
""",
                        rq_id=rid,
                        ids=row["challenge_event_ids"],
                    )
                if row["source_paper_ids"]:
                    session.run(
                        """
MATCH (rq:ResearchQuestion {rq_id:$rq_id})
UNWIND $ids AS id
MATCH (p:Paper {paper_id:id})
MERGE (rq)-[:USES_SOURCE_PAPER]->(p)
""",
                        rq_id=rid,
                        ids=row["source_paper_ids"],
                    )
                if row["inspiration_adjacent_paper_ids"]:
                    session.run(
                        """
MATCH (rq:ResearchQuestion {rq_id:$rq_id})
UNWIND $ids AS id
MATCH (p:Paper {paper_id:id})
MERGE (rq)-[:INSPIRED_BY_ADJACENT]->(p)
""",
                        rq_id=rid,
                        ids=row["inspiration_adjacent_paper_ids"],
                    )
                if row["inspiration_random_paper_ids"]:
                    session.run(
                        """
MATCH (rq:ResearchQuestion {rq_id:$rq_id})
UNWIND $ids AS id
MATCH (p:Paper {paper_id:id})
MERGE (rq)-[:INSPIRED_BY_RANDOM]->(p)
""",
                        rq_id=rid,
                        ids=row["inspiration_random_paper_ids"],
                    )
                if row["inspiration_community_paper_ids"]:
                    session.run(
                        """
MATCH (rq:ResearchQuestion {rq_id:$rq_id})
UNWIND $ids AS id
MATCH (p:Paper {paper_id:id})
MERGE (rq)-[:INSPIRED_BY_COMMUNITY]->(p)
""",
                        rq_id=rid,
                        ids=row["inspiration_community_paper_ids"],
                    )

    def list_latest_research_questions(self, domain: str | None = None, limit: int = 200) -> list[dict]:
        limit = max(1, min(2000, int(limit)))
        domain_norm = str(domain or "").strip().lower()
        cypher = """
MATCH (rq:ResearchQuestion)
WHERE ($domain = '' OR toLower(coalesce(rq.domain, '')) = $domain)
RETURN rq.rq_id AS candidate_id,
       rq.question AS question,
       rq.gap_id AS gap_id,
       rq.gap_type AS gap_type,
       rq.status AS status,
       rq.rank AS rank,
       rq.quality_score AS quality_score,
       rq.support_coverage AS support_coverage,
       rq.challenge_coverage AS challenge_coverage,
       rq.novelty_score AS novelty_score,
       rq.feasibility_score AS feasibility_score,
       rq.relevance_score AS relevance_score,
       rq.generation_mode AS generation_mode,
       rq.prompt_variant AS prompt_variant,
       rq.generation_confidence AS generation_confidence,
       rq.optimization_score AS optimization_score,
       rq.motivation AS motivation,
       rq.novelty AS novelty,
       rq.proposed_method AS proposed_method,
       rq.difference AS difference,
       rq.feasibility AS feasibility,
       rq.risk_statement AS risk_statement,
       rq.timeline AS timeline,
       rq.evaluation_metrics AS evaluation_metrics,
       rq.updated_at AS updated_at
ORDER BY coalesce(rq.updated_at, rq.created_at) DESC, coalesce(rq.rank, 999999) ASC, coalesce(rq.quality_score, 0.0) DESC
LIMIT $limit
"""
        with self._driver.session() as session:
            rows = [dict(r) for r in session.run(cypher, domain=domain_norm, limit=limit)]
        # Deduplicate by candidate_id while keeping first (latest)
        out: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            cid = str(row.get("candidate_id") or "").strip()
            if not cid or cid in seen:
                continue
            seen.add(cid)
            out.append(row)
        return out

    def get_proposition_detail(self, prop_id: str, limit_events: int = 200) -> dict:
        pid = str(prop_id or "").strip()
        if not pid:
            raise KeyError("prop_id is required")
        limit_events = max(1, min(2000, int(limit_events)))
        with self._driver.session() as session:
            row = session.run(
                """
MATCH (pr:Proposition {prop_id:$prop_id})
RETURN pr
""",
                prop_id=pid,
            ).single()
            if not row:
                raise KeyError(f"Proposition not found: {pid}")
            proposition = dict(row["pr"])

            events = [
                dict(r)
                for r in session.run(
                    """
MATCH (pr:Proposition {prop_id:$prop_id})
MATCH (e:EvidenceEvent)-[:TO_PROPOSITION]->(pr)
OPTIONAL MATCH (sc:Claim {claim_id:e.claim_id})
OPTIONAL MATCH (sp:Paper {paper_id:e.paper_id})
RETURN e.event_id AS event_id,
       e.event_type AS event_type,
       e.status AS status,
       e.confidence AS confidence,
       e.strength AS strength,
       e.event_time AS event_time,
       e.origin AS origin,
       e.source_prop_id AS source_prop_id,
       e.target_prop_id AS target_prop_id,
       sc.text AS claim_text,
       sp.paper_id AS paper_id,
       sp.title AS paper_title,
       sp.year AS paper_year
ORDER BY coalesce(e.event_time, e.created_at, '') DESC
LIMIT $limit_events
""",
                    prop_id=pid,
                    limit_events=limit_events,
                )
            ]

            neighbors = [
                dict(r)
                for r in session.run(
                    """
MATCH (a:Proposition {prop_id:$prop_id})-[r:SUPPORTS|CHALLENGES|SUPERSEDES]->(b:Proposition)
RETURN type(r) AS relation_type,
       b.prop_id AS target_prop_id,
       b.canonical_text AS target_text,
       r.score AS score,
       r.evidence_count AS evidence_count
ORDER BY coalesce(r.score, 0.0) DESC
LIMIT 200
""",
                    prop_id=pid,
                )
            ]

            return {"proposition": proposition, "events": events, "neighbors": neighbors}

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
WITH member,
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
       text AS text
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

    def list_knowledge_entities_for_propositions(self, textbook_id: str, limit: int = 5000) -> list[dict]:
        """List KnowledgeEntities eligible for Proposition mapping.

        Only proposition-type entities are returned: theory, equation,
        method, model, condition (entities that make assertive claims).
        """
        cypher = """
MATCH (t:Textbook {textbook_id: $textbook_id})-[:HAS_CHAPTER]->(c:TextbookChapter)-[:HAS_ENTITY]->(e:KnowledgeEntity)
WHERE e.entity_type IN ['theory', 'equation', 'method', 'model', 'condition']
RETURN DISTINCT e.entity_id   AS entity_id,
       e.name                 AS name,
       e.entity_type          AS entity_type,
       e.description          AS description,
       c.chapter_id           AS chapter_id
ORDER BY e.name
LIMIT $limit
"""
        with self._driver.session() as session:
            return [dict(r) for r in session.run(cypher, textbook_id=str(textbook_id), limit=int(limit))]

    def upsert_proposition_for_entity(self, items: list[dict]) -> dict[str, int]:
        """Create Proposition nodes from KnowledgeEntities and MAPS_TO edges.

        Each item: {entity_id, entity_type, prop_id, prop_key, canonical_text, source_type}
        """
        if not items:
            return {"entities": 0, "propositions": 0}
        cypher = """
UNWIND $items AS it
MATCH (e:KnowledgeEntity {entity_id: it.entity_id})
MERGE (pr:Proposition {prop_id: it.prop_id})
ON CREATE SET pr.prop_key        = it.prop_key,
              pr.canonical_text   = it.canonical_text,
              pr.created_at       = $now,
              pr.source_type      = it.source_type,
              pr.current_state    = 'stable'
SET pr.last_seen_at = $now
MERGE (e)-[m:MAPS_TO]->(pr)
SET m.mapped_at = $now,
    m.source_type = coalesce(it.source_type, 'textbook'),
    m.entity_type = coalesce(it.entity_type, '')
RETURN count(DISTINCT pr) AS prop_cnt
"""
        with self._driver.session() as session:
            result = session.run(cypher, items=items, now=datetime.now(tz=timezone.utc).isoformat())
            row = result.single()
        return {"entities": len(items), "propositions": int(row["prop_cnt"]) if row else 0}

