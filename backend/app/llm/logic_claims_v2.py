from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.ingest.models import DocumentIR
from app.llm.client import call_json, call_validated_json


_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[A-Za-z]+|\d+|[\u4e00-\u9fff]+")
_TPL_RE = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}")
_DEFAULT_EXCLUDED_SECTION_TERMS = (
    "reference",
    "references",
    "bibliography",
    "further reading",
    "acknowledg",
    "funding",
    "appendix references",
    "参考文献",
    "致谢",
)


def _render_template(template: str, vars: dict[str, Any]) -> str:
    def _sub(m: re.Match[str]) -> str:
        key = m.group(1)
        v = vars.get(key)
        if v is None:
            return ""
        if isinstance(v, (dict, list)):
            return json.dumps(v, ensure_ascii=False)
        return str(v)

    return _TPL_RE.sub(_sub, template or "")


def _norm_claim_text(text: str) -> str:
    s = _WS_RE.sub(" ", (text or "").strip())
    while s and s[-1] in ".;。；":
        s = s[:-1].rstrip()
    return s


def _claim_key_for(doi: str, text: str) -> str:
    base = (doi.strip().lower() + "\0" + _norm_claim_text(text)).encode("utf-8", errors="ignore")
    return hashlib.sha256(base).hexdigest()[:24]


def _claim_id_for(paper_id: str, claim_key: str) -> str:
    base = (paper_id + "\0" + claim_key).encode("utf-8", errors="ignore")
    return hashlib.sha256(base).hexdigest()[:24]


def _shorten(text: str, max_chars: int) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[:max_chars] + "\n[TRUNCATED]"


def _split_chunks_into_segments(chunks: list, max_chars: int) -> list[list]:
    """Split chunks into segments that fit within max_chars, respecting section boundaries."""
    if not chunks:
        return []
    segments: list[list] = []
    current_segment: list = []
    current_chars = 0
    for chunk in chunks:
        chunk_len = len(str(getattr(chunk, "text", "") or ""))
        # Start new segment if adding this chunk would exceed limit
        # (but always include at least one chunk per segment)
        if current_segment and current_chars + chunk_len > max_chars:
            segments.append(current_segment)
            current_segment = []
            current_chars = 0
        current_segment.append(chunk)
        current_chars += chunk_len + 2  # +2 for "\n\n" separator
    if current_segment:
        segments.append(current_segment)
    return segments


def _match_quotes_to_chunks(quotes: list[str], source_chunks: list) -> list[str]:
    """Match verbatim evidence quotes to chunk IDs using find_span_by_quote."""
    from app.extraction.orchestrator import find_span_by_quote

    matched_ids: list[str] = []
    for quote in quotes:
        quote_s = str(quote or "").strip()
        if not quote_s:
            continue
        for chunk in source_chunks:
            if isinstance(chunk, dict):
                text = str(chunk.get("text", "") or "")
                cid = str(chunk.get("chunk_id", "") or "").strip()
            else:
                text = str(getattr(chunk, "text", "") or "")
                cid = str(getattr(chunk, "chunk_id", "") or "").strip()
            if not text or not cid:
                continue
            _, _, mode = find_span_by_quote(quote_s, text)
            if mode in ("exact", "normalized"):
                if cid not in matched_ids:
                    matched_ids.append(cid)
                break
    return matched_ids


def _merge_segmented_logic(
    all_logic: list[dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Merge logic steps from multiple segments. Higher confidence wins; evidence fields are unioned."""
    merged: dict[str, dict[str, Any]] = {}
    for logic in all_logic:
        for sid, v in logic.items():
            if not isinstance(v, dict):
                continue
            summary = str(v.get("summary") or "").strip()
            if not summary:
                continue
            conf = float(v.get("confidence") or 0.5)
            eids = [str(e) for e in (v.get("evidence_chunk_ids") or []) if str(e).strip()]
            equotes = [str(q) for q in (v.get("evidence_quotes") or []) if str(q).strip()]
            if sid not in merged:
                merged[sid] = {
                    "summary": summary,
                    "confidence": conf,
                    "evidence_chunk_ids": list(eids),
                    "evidence_quotes": list(equotes),
                }
            else:
                existing = merged[sid]
                if conf > existing["confidence"] or (conf == existing["confidence"] and len(summary) > len(existing["summary"])):
                    existing["summary"] = summary
                    existing["confidence"] = conf
                for eid in eids:
                    if eid not in existing["evidence_chunk_ids"]:
                        existing["evidence_chunk_ids"].append(eid)
                for eq in equotes:
                    if eq not in existing.get("evidence_quotes", []):
                        existing.setdefault("evidence_quotes", []).append(eq)
    return merged


def _tokens(s: str) -> list[str]:
    toks = _TOKEN_RE.findall((s or "").lower())
    out: list[str] = []
    for t in toks:
        if re.fullmatch(r"[\u4e00-\u9fff]+", t) and len(t) > 2:
            out.extend(list(t))
        else:
            out.append(t)
    return [t for t in out if t and t not in {"the", "and", "of", "to", "in", "a", "an"}]


def _rule_int(rules: dict[str, Any], key: str, default: int, *, lo: int, hi: int) -> int:
    try:
        raw = rules.get(key, default)
        v = int(raw)
    except Exception:
        v = int(default)
    return max(lo, min(hi, v))


def _rule_float(rules: dict[str, Any], key: str, default: float, *, lo: float, hi: float) -> float:
    try:
        raw = rules.get(key, default)
        v = float(raw)
    except Exception:
        v = float(default)
    return max(lo, min(hi, v))


def _rule_bool(rules: dict[str, Any], key: str, default: bool) -> bool:
    raw = rules.get(key, None)
    if raw is None:
        return bool(default)
    if isinstance(raw, bool):
        return raw
    s = str(raw or "").strip().lower()
    if not s:
        return bool(default)
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _rule_str_list(rules: dict[str, Any], key: str) -> list[str]:
    raw = rules.get(key, None)
    if raw is None:
        return []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        s = str(item or "").strip().lower()
        if s and s not in out:
            out.append(s)
    return out


def _normalize_section_text(section: Any) -> str:
    s = str(section or "").strip().lower()
    return _WS_RE.sub(" ", s)


def _section_is_excluded(section: Any, rules: dict[str, Any]) -> bool:
    if not _rule_bool(rules, "phase1_filter_reference_sections", True):
        return False
    section_n = _normalize_section_text(section)
    if not section_n:
        return False
    section_compact = re.sub(r"[\s_\-:：]+", "", section_n)
    markers = _rule_str_list(rules, "phase1_excluded_section_terms") or list(_DEFAULT_EXCLUDED_SECTION_TERMS)
    for marker in markers:
        m = _normalize_section_text(marker)
        if not m:
            continue
        m_compact = re.sub(r"[\s_\-:：]+", "", m)
        if m in section_n:
            return True
        if m_compact and m_compact in section_compact:
            return True
    return False


def _include_chunk(chunk: Any, rules: dict[str, Any]) -> bool:
    if str(getattr(chunk, "kind", "") or "") == "heading":
        return False
    if not str(getattr(chunk, "text", "") or "").strip():
        return False
    if _section_is_excluded(getattr(chunk, "section", ""), rules):
        return False
    return True


def _lexical_top_chunks(query: str, chunks: list[dict[str, Any]], k: int = 8) -> list[dict[str, Any]]:
    q_tokens = _tokens(query)
    if not q_tokens:
        q_tokens = [query.lower().strip()]

    scored: list[tuple[float, dict[str, Any]]] = []
    for c in chunks:
        text = str(c.get("text") or "").lower()
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
    out: list[dict[str, Any]] = []
    for score, c in scored[:k]:
        snippet = (str(c.get("text") or "").strip().replace("\n", " "))
        snippet = _WS_RE.sub(" ", snippet)[:800]
        out.append({"chunk_id": c.get("chunk_id"), "snippet": snippet, "score": float(score)})
    return out


def add_logic_step_evidence(doc: DocumentIR, schema: dict[str, Any], logic: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Attach machine-picked evidence_chunk_ids to each logic step summary (cheap lexical heuristic).
    Stored into the logic dict so Neo4j can write LogicStep-[:EVIDENCED_BY]->Chunk edges.
    """
    rules = schema.get("rules") or {}
    emin = int(rules.get("logic_evidence_min") or 1)
    emax = int(rules.get("logic_evidence_max") or max(emin, 2))
    emin = max(0, min(8, emin))
    emax = max(0, min(12, emax))
    if emax and emin and emax < emin:
        emax = emin
    lexical_topk_min = _rule_int(rules, "phase1_logic_lexical_topk_min", 6, lo=1, hi=64)
    lexical_topk_multiplier = _rule_int(rules, "phase1_logic_lexical_topk_multiplier", 3, lo=1, hi=12)
    weak_score_threshold = _rule_float(rules, "phase1_logic_evidence_weak_score_threshold", 2.0, lo=0.0, hi=20.0)

    chunks = [{"chunk_id": c.chunk_id, "text": c.text} for c in doc.chunks if _include_chunk(c, rules)]

    for step_type, v in (logic or {}).items():
        if not isinstance(v, dict):
            continue
        summary = str(v.get("summary") or "").strip()
        if not summary or not emax:
            v["evidence_chunk_ids"] = []
            v["evidence_weak"] = False
            continue
        cand = _lexical_top_chunks(summary, chunks, k=max(lexical_topk_min, emax * lexical_topk_multiplier))
        picked: list[str] = []
        for c in cand:
            cid = str(c.get("chunk_id") or "").strip()
            if cid and cid not in picked:
                picked.append(cid)
            if len(picked) >= emax:
                break

        weak = False
        top_score = float(cand[0].get("score") or 0.0) if cand else 0.0
        if not picked:
            weak = True
        elif top_score < weak_score_threshold:
            weak = True

        v["evidence_chunk_ids"] = picked[:emax]
        v["evidence_weak"] = bool(weak)

    return logic


def extract_logic_and_claims_v2(
    doc: DocumentIR,
    paper_id: str,
    schema: dict[str, Any],
    max_chars: int = 18000,
    *,
    logic_only: bool = False,
) -> dict[str, Any]:
    """
    Schema-driven extraction:
    - logic chain: summaries for enabled steps
    - claims: 24-48 (or fewer if evidence is insufficient), each bound to exactly one step + multi-select kinds
    When logic_only=True, skip claim extraction to save tokens (claims come from chunk-level extractor).
    """
    title = doc.paper.title or doc.paper.title_alt or doc.paper.paper_source
    authors = ", ".join(doc.paper.authors[:8]) if doc.paper.authors else ""
    doi = (doc.paper.doi or "").strip().lower()
    year = doc.paper.year or ""

    steps_all = list(schema.get("steps") or [])
    steps = [s for s in steps_all if bool((s or {}).get("enabled", True))]
    step_ids = [str(s.get("id") or "") for s in steps if str(s.get("id") or "").strip()]
    if not step_ids:
        step_ids = [str(s.get("id") or "") for s in steps_all if str(s.get("id") or "").strip()]
    kind_ids = [str(k.get("id") or "") for k in (schema.get("claim_kinds") or []) if bool((k or {}).get("enabled", True))]
    rules = schema.get("rules") or {}
    cmin = int(rules.get("claims_per_paper_min") or 24)
    cmax = int(rules.get("claims_per_paper_max") or max(cmin, 48))
    doc_chars_max = int(rules.get("phase1_doc_chars_max") or max_chars)
    doc_chars_max = max(2000, min(120000, doc_chars_max))
    evidence_candidate_topk = _rule_int(rules, "phase1_evidence_lexical_topk", 10, lo=1, hi=64)
    verify_candidates_max = _rule_int(rules, "phase1_evidence_verify_candidates_max", 6, lo=1, hi=16)

    source_chunks = [c for c in doc.chunks if _include_chunk(c, rules)]
    if not source_chunks:
        source_chunks = [c for c in doc.chunks if str(getattr(c, "kind", "") or "") != "heading" and str(c.text or "").strip()]

    full_body = "\n\n".join(str(c.text or "") for c in source_chunks)
    needs_segmentation = len(full_body) > doc_chars_max

    # --- Helper: run one extraction pass on a body segment ---
    def _run_one_pass(
        segment_body: str,
        claim_min: int,
        claim_max: int,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        seg_body = _shorten(segment_body, max_chars=doc_chars_max)

        default_system = (
            "You extract a paper's reasoning structure for a research knowledge graph.\n"
            "Return STRICT JSON only (no prose, no Markdown).\n"
            "\n"
            "GROUNDING / FAITHFULNESS:\n"
            "- Be strictly faithful to the provided paper text.\n"
            "- Do NOT invent details, numbers, conditions, or causal claims.\n"
            "- If something is not explicitly supported, omit it (preferred) or lower confidence.\n"
            "\n"
            "SCIENTIFIC VALUE (CRITICAL):\n"
            "- Extract ONLY scientific contributions, methods, findings, and conclusions.\n"
            "- DO NOT extract meta-information such as:\n"
            "  * Author names, affiliations, correspondence addresses\n"
            "  * Submission/acceptance/publication dates\n"
            "  * Funding sources, grant numbers, acknowledgments\n"
            "  * Journal names, DOIs, paper identifiers\n"
            "  * Conflict of interest statements\n"
            "  * Dataset availability, code repository links (unless core to the method)\n"
            "- Focus on WHAT was discovered/proposed, not WHO/WHEN/WHERE published.\n"
            "- When encountering pure meta-information chunks, output empty claims array.\n"
            "\n"
            "LANGUAGE / STYLE:\n"
            "- Use the same language as the paper text.\n"
            "- Write COMPLETE sentences only (no fragments, no missing subjects/verbs).\n"
            "- Keep technical symbols/variables exactly as in the paper.\n"
            "\n"
            "DIFFERENT OUTPUT GRANULARITIES:\n"
            "1) logic: for EACH allowed step_type, write a DETAILED mini-paragraph summary.\n"
            "   - 2-6 complete sentences (NOT a single sentence).\n"
            "   - Include key entities, methods, assumptions/conditions, and important numbers/definitions if present.\n"
            "   - Include evidence_quotes: 1-3 verbatim quotes (20-200 chars each) copied directly from the paper text that support this summary.\n"
            + (
                "2) claims: write concise, atomic KEY POINTS.\n"
                "   - 1-2 complete sentences each.\n"
                "   - Each claim must be specific and directly supported by the text.\n"
                "   - Avoid duplicating the logic summaries verbatim.\n"
                "\n"
                "SCHEMA RULES:\n"
                "- Each claim MUST belong to exactly ONE step_type (from the allowed list).\n"
                "- Each claim MUST have claim_kinds as a LIST (multi-select) chosen from allowed kinds (prefer 1-3 kinds).\n"
                "- Confidence values must be in [0,1].\n"
                if not logic_only else
                "\nOutput logic steps ONLY. Do NOT output claims.\n"
                "- Confidence values must be in [0,1].\n"
            )
        )
        if logic_only:
            default_user = (
                f"Paper metadata:\nTitle: {title}\nAuthors: {authors}\nYear: {year}\nDOI: {doi}\n\n"
                f"Allowed step types: {step_ids}\n\n"
                "Paper text (extracted from Markdown):\n"
                f"{seg_body}\n\n"
                "Output JSON schema (STRICT):\n"
                "{\n"
                '  "logic": {\n'
                '    "<StepType>": {"summary": "2-6 full sentences...", "confidence": 0.0, "evidence_quotes": ["verbatim quote..."]}\n'
                "  }\n"
                "}\n"
            )
        else:
            default_user = (
                f"Paper metadata:\nTitle: {title}\nAuthors: {authors}\nYear: {year}\nDOI: {doi}\n\n"
                f"Allowed step types: {step_ids}\n"
                f"Allowed claim kinds: {kind_ids}\n"
                f"Target number of claims: {claim_min}-{claim_max}\n\n"
                "Paper text (extracted from Markdown):\n"
                f"{seg_body}\n\n"
                "Output JSON schema (STRICT):\n"
                "{\n"
                '  "logic": {\n'
                '    "<StepType>": {"summary": "2-6 full sentences...", "confidence": 0.0, "evidence_quotes": ["verbatim quote..."]}\n'
                "  },\n"
                '  "claims": [\n'
                '    {"text":"1-2 full sentences...","confidence":0.0,"step_type":"<StepType>","claim_kinds":["KindA","KindB"]}\n'
                "  ]\n"
                "}\n"
            )

        prompts = schema.get("prompts") or {}
        system = str(prompts.get("logic_claims_system") or "").strip() or default_system
        user_t = str(prompts.get("logic_claims_user_template") or "").strip()
        if user_t:
            user = _render_template(
                user_t,
                {
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "doi": doi,
                    "step_ids": step_ids,
                    "kind_ids": kind_ids,
                    "cmin": claim_min,
                    "cmax": claim_max,
                    "body": seg_body,
                },
            )
        else:
            user = default_user

        from app.llm.schemas import LogicClaimsResponse

        try:
            validated = call_validated_json(system, user, LogicClaimsResponse)
            out = validated.model_dump()
        except Exception:
            out = call_json(system, user)
        logic_in = out.get("logic") or {}
        claims_in = out.get("claims") or []

        seg_logic: dict[str, dict[str, Any]] = {}
        for sid in step_ids:
            v = (logic_in.get(sid) if isinstance(logic_in, dict) else {}) or {}
            summary = str(v.get("summary") or "").strip()
            if not summary:
                continue
            # Read evidence_quotes from LLM output, match to chunks programmatically
            raw_quotes = v.get("evidence_quotes") or []
            if not isinstance(raw_quotes, list):
                raw_quotes = [raw_quotes] if isinstance(raw_quotes, str) else []
            evidence_quotes = [str(q).strip() for q in raw_quotes if str(q).strip()]
            matched_chunk_ids = _match_quotes_to_chunks(evidence_quotes, source_chunks)
            # Also accept legacy evidence_chunk_ids if they exist in source chunks
            source_cid_set = {str(getattr(c, "chunk_id", "") or "").strip() for c in source_chunks}
            for eid in (v.get("evidence_chunk_ids") or []):
                s = str(eid or "").strip()
                if s and s in source_cid_set and s not in matched_chunk_ids:
                    matched_chunk_ids.append(s)
            seg_logic[sid] = {
                "summary": summary,
                "confidence": float(v.get("confidence") or 0.5),
                "evidence_chunk_ids": matched_chunk_ids,
                "evidence_quotes": evidence_quotes,
            }

        seg_claims: list[dict[str, Any]] = []
        if not logic_only:
            for c in claims_in:
                if not isinstance(c, dict):
                    continue
                text = str(c.get("text") or "").strip()
                if not text:
                    continue
                step_type = str(c.get("step_type") or "").strip()
                if step_type not in allowed_steps:
                    continue
                kinds_raw = c.get("claim_kinds")
                kinds: list[str] = []
                if isinstance(kinds_raw, list):
                    for k in kinds_raw:
                        kk = str(k or "").strip()
                        if kk and kk in allowed_kinds and kk not in kinds:
                            kinds.append(kk)
                conf = float(c.get("confidence") or 0.5)
                key = _claim_key_for(doi, text) if doi else hashlib.sha256((paper_id + "\0" + text).encode("utf-8", errors="ignore")).hexdigest()[:24]
                seg_claims.append(
                    {
                        "claim_key": key,
                        "claim_id": _claim_id_for(paper_id, key),
                        "text": text,
                        "confidence": conf,
                        "step_type": step_type,
                        "kinds": kinds,
                    }
                )
        return seg_logic, seg_claims
    # --- End helper ---

    # Single-pass or segmented extraction
    if not needs_segmentation:
        norm_logic, norm_claims = _run_one_pass(full_body, cmin, cmax)
    else:
        segments = _split_chunks_into_segments(source_chunks, doc_chars_max)
        all_segment_logic: list[dict[str, dict[str, Any]]] = []
        norm_claims = []
        claims_per_segment = max(4, cmin // max(1, len(segments)))
        claims_max_per_segment = max(8, cmax // max(1, len(segments)))
        for seg_chunks in segments:
            seg_body = "\n\n".join(str(c.text or "") for c in seg_chunks)
            seg_logic, seg_claims = _run_one_pass(seg_body, claims_per_segment, claims_max_per_segment)
            all_segment_logic.append(seg_logic)
            norm_claims.extend(seg_claims)
        norm_logic = _merge_segmented_logic(all_segment_logic)

    return {"logic": norm_logic, "claims": norm_claims, "raw": {}}


def add_evidence_and_targets(
    doc: DocumentIR,
    schema: dict[str, Any],
    claims: list[dict[str, Any]],
    cite_rec: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Populate:
    - evidence_chunk_ids (machine, 1-2 by default)
    - targets_paper_ids (for certain kinds, from citation evidence in the same chunks)
    """
    rules = schema.get("rules") or {}
    emin = int(rules.get("machine_evidence_min") or 1)
    emax = int(rules.get("machine_evidence_max") or max(emin, 2))
    evidence_verification = str(rules.get("evidence_verification") or "llm")
    targets_max = int(rules.get("targets_per_claim_max") or 3)
    require_target_kinds = set(rules.get("require_targets_for_kinds") or [])
    evidence_candidate_topk = _rule_int(rules, "phase1_evidence_lexical_topk", 10, lo=1, hi=64)
    verify_candidates_max = _rule_int(rules, "phase1_evidence_verify_candidates_max", 6, lo=1, hi=16)

    chunks = [
        {
            "chunk_id": c.chunk_id,
            "text": c.text,
            "kind": c.kind,
            "section": c.section,
            "start_line": c.span.start_line,
            "end_line": c.span.end_line,
        }
        for c in doc.chunks
        if _include_chunk(c, rules)
    ]

    cited_by_chunk: dict[str, list[dict[str, Any]]] = {}
    if cite_rec:
        for cr in cite_rec.get("cites_resolved") or []:
            cited_paper_id = cr.get("cited_paper_id")
            if not cited_paper_id:
                continue
            for cid in cr.get("evidence_chunk_ids") or []:
                cited_by_chunk.setdefault(str(cid), []).append(
                    {"cited_paper_id": str(cited_paper_id), "total_mentions": int(cr.get("total_mentions") or 0)}
                )

    # 1) Build lexical candidates for all claims first (cheap).
    candidates_by_key: dict[str, list[dict[str, Any]]] = {}
    for cl in claims:
        q = str(cl.get("text") or "")
        key = str(cl.get("claim_key") or "")
        candidates_by_key[key] = _lexical_top_chunks(q, chunks, k=evidence_candidate_topk)

    # 2) Optional LLM verification in small batches to reduce calls.
    if evidence_verification == "llm":
        batch_size = int(rules.get("phase1_evidence_verify_batch_size") or 6)
        batch_size = max(1, min(32, batch_size))
        keys = [str(c.get("claim_key") or "") for c in claims]
        verified: dict[str, dict[str, Any]] = {}
        for i in range(0, len(keys), batch_size):
            batch_keys = [k for k in keys[i : i + batch_size] if k]
            if not batch_keys:
                continue
            payload = []
            for k in batch_keys:
                cl = next((x for x in claims if str(x.get("claim_key") or "") == k), None)
                if not cl:
                    continue
                cand = candidates_by_key.get(k, [])[:verify_candidates_max]
                payload.append({"claim_key": k, "text": str(cl.get("text") or ""), "candidates": cand})
            if not payload:
                continue
            try:
                prompts = schema.get("prompts") or {}
                default_system = (
                    "Pick evidence chunks for claims. Return STRICT JSON only (no prose).\n"
                    "- Pick chunks that DIRECTLY support the claim wording.\n"
                    "- Prefer chunks containing the key definition/number/equation mentioned.\n"
                    "- If evidence is weak/indirect, still pick the best available and set weak=true.\n"
                )
                default_user = (
                    f"Pick {emin}-{emax} chunk_id(s) per claim from its candidates.\n"
                    "If none strongly supports it, still pick best 1 and set weak=true.\n\n"
                    "Input claims JSON:\n"
                    f"{payload}\n\n"
                    "Output JSON schema:\n"
                    '{ "items": [ {"claim_key":"...","evidence_chunk_ids":["..."],"weak":false} ] }\n'
                )
                system = str(prompts.get("evidence_pick_system") or "").strip() or default_system
                user_t = str(prompts.get("evidence_pick_user_template") or "").strip()
                if user_t:
                    user = _render_template(
                        user_t,
                        {
                            "emin": emin,
                            "emax": emax,
                            "payload_json": json.dumps(payload, ensure_ascii=False),
                        },
                    )
                else:
                    user = default_user
                from app.llm.schemas import EvidencePickResponse

                try:
                    validated_ep = call_validated_json(system, user, EvidencePickResponse)
                    out = validated_ep.model_dump()
                except Exception:
                    out = call_json(system, user)
                items = out.get("items") or []
                if isinstance(items, list):
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        k = str(it.get("claim_key") or "")
                        if not k:
                            continue
                        ids = it.get("evidence_chunk_ids") or []
                        picked: list[str] = []
                        if isinstance(ids, list):
                            for x in ids[: max(1, emax)]:
                                s = str(x or "").strip()
                                if s:
                                    picked.append(s)
                        verified[k] = {"evidence_chunk_ids": picked, "weak": bool(it.get("weak") or False)}
            except Exception:
                # ignore this batch; will fallback to lexical
                pass

        # apply verified results
        for cl in claims:
            k = str(cl.get("claim_key") or "")
            v = verified.get(k)
            if not v:
                continue
            cl["evidence_chunk_ids"] = list(v.get("evidence_chunk_ids") or [])
            cl["evidence_weak"] = bool(v.get("weak") or False)

    # 3) Fill remaining claims with lexical fallback.
    for cl in claims:
        q = str(cl.get("text") or "")
        candidates = candidates_by_key.get(str(cl.get("claim_key") or ""), []) or _lexical_top_chunks(
            q,
            chunks,
            k=evidence_candidate_topk,
        )
        picked = list(cl.get("evidence_chunk_ids") or [])
        weak = bool(cl.get("evidence_weak") or False)
        if not picked and candidates:
            weak = True
            picked = [str(candidates[0]["chunk_id"])]
            if emax >= 2 and len(candidates) > 1:
                picked.append(str(candidates[1]["chunk_id"]))
        cl["evidence_chunk_ids"] = picked[: max(1, emax)] if picked else []
        cl["evidence_weak"] = bool(weak)

        kinds = set(cl.get("kinds") or [])
        if kinds.intersection(require_target_kinds):
            targets: dict[str, int] = {}
            for cid in (cl.get("evidence_chunk_ids") or []):
                for item in cited_by_chunk.get(str(cid), []):
                    pid = str(item.get("cited_paper_id") or "")
                    if not pid:
                        continue
                    targets[pid] = max(targets.get(pid, 0), int(item.get("total_mentions") or 0))
            ordered = sorted(targets.items(), key=lambda kv: kv[1], reverse=True)
            cl["targets_paper_ids"] = [pid for pid, _ in ordered[: max(0, targets_max)]]
        else:
            cl["targets_paper_ids"] = []

    return claims
