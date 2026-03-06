from __future__ import annotations

import hashlib
import json
import re

from app.ingest.models import DocumentIR
from app.llm.client import call_json


IMRAD_ORDER = ["Background", "Problem", "Method", "Experiment", "Result", "Conclusion"]
_WS_RE = re.compile(r"\s+")


def _norm_claim_text(text: str) -> str:
    s = _WS_RE.sub(" ", (text or "").strip())
    while s and s[-1] in ".;。；":
        s = s[:-1].rstrip()
    return s


def _shorten(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[:max_chars] + "\n[TRUNCATED]"


def extract_imrad_and_claims(doc: DocumentIR, max_chars: int = 18000) -> dict:
    """
    DeepSeek extracts:
    - IMRaD chain: 6 summaries
    - claims: 3-8 concise claims
    """
    title = doc.paper.title or doc.paper.title_alt or doc.paper.paper_source
    authors = ", ".join(doc.paper.authors[:8]) if doc.paper.authors else ""
    doi = doc.paper.doi or ""
    year = doc.paper.year or ""

    # Build evidence text from content chunks (exclude headings).
    body = "\n\n".join(c.text for c in doc.chunks if c.kind != "heading")
    body = _shorten(body, max_chars=max_chars)

    system = (
        "You extract a paper's reasoning structure for a mechanics knowledge graph.\n"
        "Return STRICT JSON only, no prose.\n"
        "Use these IMRaD step types exactly: Background, Problem, Method, Experiment, Result, Conclusion.\n"
        "Write each summary in 2-5 sentences. Be faithful to the evidence.\n"
        "Also output 3-8 key claims as short bullet-like sentences (no numbering).\n"
        "If evidence is missing, say so explicitly in the summary text."
    )
    user = (
        f"Paper metadata:\nTitle: {title}\nAuthors: {authors}\nYear: {year}\nDOI: {doi}\n\n"
        f"Paper text (extracted from Markdown):\n{body}\n\n"
        "Output JSON schema:\n"
        "{\n"
        '  "imrad": {\n'
        '    "Background": {"summary": "...", "confidence": 0.0},\n'
        '    "Problem": {"summary": "...", "confidence": 0.0},\n'
        '    "Method": {"summary": "...", "confidence": 0.0},\n'
        '    "Experiment": {"summary": "...", "confidence": 0.0},\n'
        '    "Result": {"summary": "...", "confidence": 0.0},\n'
        '    "Conclusion": {"summary": "...", "confidence": 0.0}\n'
        "  },\n"
        '  "claims": [ {"text": "...", "confidence": 0.0} ]\n'
        "}\n"
    )

    out = call_json(system, user)
    # minimal normalization
    imrad = out.get("imrad") or {}
    claims = out.get("claims") or []
    norm_imrad = {}
    for k in IMRAD_ORDER:
        v = imrad.get(k) or {}
        norm_imrad[k] = {
            "summary": (v.get("summary") or "").strip(),
            "confidence": float(v.get("confidence") or 0.5),
        }
    norm_claims = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        text = (c.get("text") or "").strip()
        if not text:
            continue
        conf = float(c.get("confidence") or 0.5)
        claim_id = hashlib.sha256((doc.paper.md_path + "\0" + text).encode("utf-8", errors="ignore")).hexdigest()[:24]
        doi = (doc.paper.doi or "").strip().lower()
        claim_key = hashlib.sha256((doi + "\0" + _norm_claim_text(text)).encode("utf-8", errors="ignore")).hexdigest()[:24]
        norm_claims.append({"claim_id": claim_id, "claim_key": claim_key, "text": text, "confidence": conf})

    return {"imrad": norm_imrad, "claims": norm_claims, "raw": out}
