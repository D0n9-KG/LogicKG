from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


_TOKEN_RE = re.compile(r"[A-Za-z]+|\d+|[\u4e00-\u9fff]+")


def _tokens(s: str) -> list[str]:
    toks = _TOKEN_RE.findall((s or "").lower())
    out: list[str] = []
    for t in toks:
        if re.fullmatch(r"[\u4e00-\u9fff]+", t) and len(t) > 2:
            # crude split to increase recall for Chinese phrases
            out.extend(list(t))
        else:
            out.append(t)
    return [t for t in out if t and t not in {"the", "and", "of", "to", "in", "a", "an"}]


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    paper_source: str
    md_path: str
    start_line: int
    end_line: int
    section: str | None
    kind: str
    snippet: str
    score: float


def latest_run_dir(runs_dir: Path) -> Path:
    latest = runs_dir / "LATEST"
    if not latest.exists():
        raise FileNotFoundError("No runs yet. Call /ingest/path first.")
    run_id = latest.read_text(encoding="utf-8").strip()
    rd = runs_dir / run_id
    if not rd.exists():
        raise FileNotFoundError(f"Run dir missing: {rd}")
    return rd


def load_chunks_from_run(run_dir: Path) -> list[dict]:
    # Read all *.document_ir.json files.
    chunks: list[dict] = []
    for p in run_dir.glob("*.document_ir.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        for c in data.get("chunks") or []:
            if c.get("kind") == "heading":
                continue
            span = c.get("span") or {}
            chunks.append(
                {
                    "chunk_id": c.get("chunk_id"),
                    "paper_source": c.get("paper_source"),
                    "md_path": c.get("md_path"),
                    "start_line": span.get("start_line"),
                    "end_line": span.get("end_line"),
                    "section": c.get("section"),
                    "kind": c.get("kind"),
                    "text": c.get("text") or "",
                }
            )
    return chunks


def lexical_retrieve(question: str, chunks: list[dict], k: int = 8) -> list[RetrievedChunk]:
    q_tokens = _tokens(question)
    if not q_tokens:
        q_tokens = [question.lower().strip()]

    scored: list[tuple[float, dict]] = []
    for c in chunks:
        text = (c.get("text") or "").lower()
        if not text:
            continue
        s = 0.0
        for t in q_tokens:
            if not t:
                continue
            cnt = text.count(t)
            if cnt:
                s += 1.0 + min(5, cnt) * 0.3
        if s > 0:
            scored.append((s, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[RetrievedChunk] = []
    for score, c in scored[:k]:
        snippet = (c.get("text") or "").strip().replace("\n", " ")
        snippet = re.sub(r"\s+", " ", snippet)[:1200]
        out.append(
            RetrievedChunk(
                chunk_id=str(c.get("chunk_id")),
                paper_source=str(c.get("paper_source")),
                md_path=str(c.get("md_path")),
                start_line=int(c.get("start_line") or 0),
                end_line=int(c.get("end_line") or 0),
                section=c.get("section"),
                kind=str(c.get("kind") or "block"),
                snippet=snippet,
                score=float(score),
            )
        )
    return out

