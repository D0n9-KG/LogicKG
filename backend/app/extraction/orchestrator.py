from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from app.ingest.models import DocumentIR
from app.text_normalization import fold_symbol_confusables


logger = logging.getLogger(__name__)


LogicExtractorFn = Callable[..., dict[str, Any]]
ClaimExtractorFn = Callable[..., list[dict[str, Any]]]


_WS_RE = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[A-Za-z]+|\d+|[\u4e00-\u9fff]+")
_TPL_RE = re.compile(r"\{\{\s*([A-Za-z][A-Za-z0-9_]*)\s*\}\}")
_STOP_TOKENS = {
    "the",
    "and",
    "of",
    "to",
    "in",
    "a",
    "an",
    "this",
    "that",
    "these",
    "those",
    "our",
    "their",
    "paper",
    "method",
    "result",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "who",
    "when",
    "where",
    "can",
    "could",
    "may",
    "might",
    "will",
    "would",
    "should",
    "than",
    "via",
}
_POLARITY_POS_TOKENS = {
    "increase",
    "increases",
    "increased",
    "improve",
    "improves",
    "improved",
    "better",
    "higher",
    "gain",
    "gains",
    "boost",
    "boosts",
    "enhance",
    "enhanced",
    "outperform",
    "outperforms",
}
_POLARITY_NEG_TOKENS = {
    "decrease",
    "decreases",
    "decreased",
    "reduce",
    "reduces",
    "reduced",
    "lower",
    "worse",
    "worsen",
    "worsened",
    "drop",
    "decline",
    "declines",
    "declined",
    "weaker",
}
_POLARITY_POS_ZH = ("提高", "增加", "增大", "改善", "优于", "更高", "增强")
_POLARITY_NEG_ZH = ("降低", "减少", "减小", "恶化", "劣于", "更低", "下降", "削弱")
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


def _rule_float(rules: dict[str, Any], key: str, default: float) -> float:
    raw = rules.get(key, None)
    if raw is None:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _rule_int(rules: dict[str, Any], key: str, default: int) -> int:
    raw = rules.get(key, None)
    if raw is None:
        return int(default)
    try:
        return int(raw)
    except Exception:
        return int(default)


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
    for x in raw:
        s = str(x or "").strip().lower()
        if s and s not in out:
            out.append(s)
    return out


def _rule_choice(rules: dict[str, Any], key: str, choices: tuple[str, ...], default: str) -> str:
    value = str(rules.get(key, default) or "").strip().lower()
    if value in choices:
        return value
    return str(default).strip().lower()


def _effective_stop_tokens(rules: dict[str, Any] | None) -> set[str]:
    r = rules or {}
    out = set(_STOP_TOKENS)
    out.update(_rule_str_list(r, "phase2_conflict_stop_terms_en"))
    out.update(_rule_str_list(r, "phase2_conflict_stop_terms_zh"))
    return out


def _normalize_section_text(section: Any) -> str:
    text = str(section or "").strip().lower()
    return _WS_RE.sub(" ", text)


def _normalized_section_markers(rules: dict[str, Any] | None) -> list[str]:
    configured = _rule_str_list(rules or {}, "phase1_excluded_section_terms")
    markers = configured or list(_DEFAULT_EXCLUDED_SECTION_TERMS)
    out: list[str] = []
    for marker in markers:
        s = _normalize_section_text(marker)
        if s and s not in out:
            out.append(s)
    return out


def _section_is_excluded(section: Any, rules: dict[str, Any] | None) -> bool:
    rr = rules or {}
    if not _rule_bool(rr, "phase1_filter_reference_sections", True):
        return False
    s = _normalize_section_text(section)
    if not s:
        return False
    s_compact = re.sub(r"[\s_\-:：]+", "", s)
    for marker in _normalized_section_markers(rr):
        m_compact = re.sub(r"[\s_\-:：]+", "", marker)
        if marker in s:
            return True
        if m_compact and m_compact in s_compact:
            return True
    return False


def _is_candidate_chunk(chunk: Any, rules: dict[str, Any] | None) -> bool:
    if str(getattr(chunk, "kind", "") or "") == "heading":
        return False
    if not str(getattr(chunk, "text", "") or "").strip():
        return False
    if _section_is_excluded(getattr(chunk, "section", ""), rules):
        return False
    return True


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


def _norm_text(text: str) -> str:
    s = _WS_RE.sub(" ", (text or "").strip())
    while s and s[-1] in ".;。；":
        s = s[:-1].rstrip()
    return s


def _claim_key_for(doi: str, paper_id: str, text: str) -> str:
    norm = _norm_text(text).lower()
    if doi.strip():
        seed = (doi.strip().lower() + "\0" + norm).encode("utf-8", errors="ignore")
    else:
        seed = (paper_id + "\0" + norm).encode("utf-8", errors="ignore")
    return hashlib.sha256(seed).hexdigest()[:24]


def _claim_id_for(paper_id: str, claim_key: str) -> str:
    seed = (paper_id + "\0" + claim_key).encode("utf-8", errors="ignore")
    return hashlib.sha256(seed).hexdigest()[:24]


def _json_dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _enabled_step_ids(schema: dict[str, Any]) -> list[str]:
    steps_all = list(schema.get("steps") or [])
    enabled = [s for s in steps_all if bool((s or {}).get("enabled", True))]
    step_ids = [str(s.get("id") or "").strip() for s in enabled if str(s.get("id") or "").strip()]
    if step_ids:
        return step_ids
    return [str(s.get("id") or "").strip() for s in steps_all if str(s.get("id") or "").strip()]


def _enabled_kind_ids(schema: dict[str, Any]) -> list[str]:
    kinds = list(schema.get("claim_kinds") or [])
    out = []
    for k in kinds:
        if not bool((k or {}).get("enabled", True)):
            continue
        kid = str((k or {}).get("id") or "").strip()
        if kid:
            out.append(kid)
    return out


def _logic_chunk_catalog(
    doc: DocumentIR,
    max_chunks: int = 56,
    max_chars: int = 420,
    *,
    rules: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    cap_chunks = max(8, min(200, int(max_chunks)))
    cap_chars = max(120, min(1200, int(max_chars)))
    for c in doc.chunks:
        if not _is_candidate_chunk(c, rules):
            continue
        text = _WS_RE.sub(" ", str(c.text or "").strip())
        if not text:
            continue
        rows.append(
            {
                "chunk_id": str(c.chunk_id),
                "section": str(c.section or ""),
                "text": text[:cap_chars],
            }
        )
        if len(rows) >= cap_chunks:
            break
    return rows


def _default_logic_extractor(*, doc: DocumentIR, paper_id: str, schema: dict[str, Any]) -> dict[str, Any]:
    from app.llm.logic_claims_v2 import extract_logic_and_claims_v2

    out = extract_logic_and_claims_v2(doc=doc, paper_id=paper_id, schema=schema, logic_only=True)
    logic = out.get("logic") or {}
    step_order = _enabled_step_ids(schema)

    # Filter empty logic steps: remove steps with empty summary AND empty evidence
    filtered_logic = {
        sid: data for sid, data in logic.items()
        if (data.get("summary_machine") or data.get("summary") or "").strip()
           or data.get("evidence_chunk_ids")
    }

    return {"logic": filtered_logic, "step_order": step_order}


def _priority_chunks(
    doc: DocumentIR,
    logic: dict[str, Any],
    max_chunks: int = 40,
    *,
    rules: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    by_id = {c.chunk_id: c for c in doc.chunks if _is_candidate_chunk(c, rules)}
    pri: list[str] = []
    for _, v in (logic or {}).items():
        if not isinstance(v, dict):
            continue
        for cid in (v.get("evidence_chunk_ids") or []):
            s = str(cid or "").strip()
            if s and s not in pri:
                pri.append(s)

    ordered = []
    for cid in pri:
        ch = by_id.get(cid)
        if ch:
            ordered.append(ch)

    for ch in by_id.values():
        if ch in ordered:
            continue
        ordered.append(ch)
    return [{"chunk_id": c.chunk_id, "text": c.text, "section": c.section} for c in ordered[: max(1, int(max_chunks))]]


def _truncate_to_sentence_boundary(text: str, max_chars: int) -> str:
    """Truncate *text* at a sentence boundary not exceeding *max_chars* characters.

    Tries common sentence-ending punctuation (both ASCII and CJK). Falls back
    to a hard character truncation when no boundary is found in the window.
    """
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    for punct in (".", "。", "!", "?", "！", "？", ";", "；"):
        pos = window.rfind(punct)
        if pos > max_chars // 2:  # at least half the budget must be used
            return window[: pos + 1].rstrip()
    return window


def _validate_claim_span(chunk_text: str, char_start: Any, char_end: Any) -> tuple[int, int]:
    """Validate LLM-provided span indices against *chunk_text*.

    Returns the validated ``(char_start, char_end)`` tuple, or ``(-1, -1)``
    when the span is invalid (out-of-bounds, reversed, or non-integer).
    """
    try:
        s, e = int(char_start), int(char_end)
    except (TypeError, ValueError):
        return (-1, -1)
    n = len(chunk_text)
    if s < 0 or e <= s or e > n:
        return (-1, -1)
    return (s, e)


def _collapse_ws_with_map(text: str) -> tuple[str, list[int]]:
    """Collapse consecutive whitespace to single spaces and keep source index map.

    Returns (collapsed_text, source_index_map) where source_index_map[i] is the
    index in the original text corresponding to collapsed_text[i].
    """
    out_chars: list[str] = []
    out_to_src: list[int] = []
    pending_space = False
    for src_idx, ch in enumerate(text or ""):
        if ch.isspace():
            if out_chars:  # Don't add leading space
                pending_space = True
            continue
        if pending_space:
            out_chars.append(" ")
            out_to_src.append(src_idx)
            pending_space = False
        out_chars.append(ch)
        out_to_src.append(src_idx)
    return ("".join(out_chars), out_to_src)


def find_span_by_quote(evidence_quote: str, chunk_text: str) -> tuple[int, int, str]:
    """Locate evidence quote inside chunk text.

    Returns (span_start, span_end, match_mode), where match_mode is one of:
    "invalid_len", "exact", "normalized", "none".
    """
    quote = str(evidence_quote or "").strip()
    chunk = str(chunk_text or "")
    if not quote or not chunk:
        return (-1, -1, "none")

    qlen = len(quote)
    if qlen < 20 or qlen > 220:
        return (-1, -1, "invalid_len")

    # 1) Exact match
    pos = chunk.find(quote)
    if pos >= 0:
        return (pos, pos + len(quote), "exact")

    # 2) Normalized match with index mapping back to original chunk
    try:
        from app.text_normalization import normalize_formula_for_matching
    except Exception:
        return (-1, -1, "none")

    def _normalize_with_map(src: str) -> tuple[str, list[int]]:
        norm_chars: list[str] = []
        norm_to_src: list[int] = []
        for src_idx, ch in enumerate(src):
            try:
                piece = normalize_formula_for_matching(ch)
            except Exception:
                piece = ch
            piece_s = str(piece or "")
            if not piece_s:
                continue
            for out_ch in piece_s:
                norm_chars.append(out_ch)
                norm_to_src.append(src_idx)
        return ("".join(norm_chars), norm_to_src)

    quote_norm, _ = _normalize_with_map(quote)
    chunk_norm, chunk_norm_to_src = _normalize_with_map(chunk)
    if not quote_norm or not chunk_norm or not chunk_norm_to_src:
        return (-1, -1, "none")

    quote_c, _ = _collapse_ws_with_map(quote_norm)
    chunk_c, chunk_c_to_norm = _collapse_ws_with_map(chunk_norm)
    if not quote_c or not chunk_c or not chunk_c_to_norm:
        return (-1, -1, "none")

    pos = chunk_c.find(quote_c)
    if pos < 0:
        pos = chunk_c.lower().find(quote_c.lower())
    if pos < 0:
        return (-1, -1, "none")

    end_pos = pos + len(quote_c) - 1
    if end_pos >= len(chunk_c_to_norm):
        return (-1, -1, "none")

    norm_start = chunk_c_to_norm[pos]
    norm_end = chunk_c_to_norm[end_pos]
    if norm_start < 0 or norm_end < norm_start:
        return (-1, -1, "none")
    if norm_start >= len(chunk_norm_to_src) or norm_end >= len(chunk_norm_to_src):
        return (-1, -1, "none")

    start = chunk_norm_to_src[norm_start]
    end = chunk_norm_to_src[norm_end] + 1
    if start < 0 or end <= start or end > len(chunk):
        return (-1, -1, "none")
    return (start, end, "normalized")



def _extract_claims_from_chunk_llm(
    *,
    chunk_text: str,
    step_ids: list[str],
    kind_ids: list[str],
    max_claims: int,
    schema: dict[str, Any],
) -> list[dict[str, Any]]:
    from app.llm.client import call_json

    rules = schema.get("rules") or {}
    prompts = schema.get("prompts") or {}
    text = (chunk_text or "").strip()
    if not text:
        return []
    chunk_chars_max = max(200, min(12000, _rule_int(rules, "phase1_chunk_chars_max", 1800)))
    if len(text) > chunk_chars_max:
        text = _truncate_to_sentence_boundary(text, chunk_chars_max)
    default_system = (
        "Extract atomic claims from one paper chunk. Return STRICT JSON only.\n"
        "\n"
        "GROUNDING:\n"
        "- Each claim must be directly supported by the provided chunk text.\n"
        "- Do not invent information outside this chunk.\n"
        "\n"
        "EVIDENCE QUOTE (REQUIRED):\n"
        "- evidence_quote is REQUIRED for every claim.\n"
        "- evidence_quote must be copied VERBATIM from chunk text (no paraphrase, no symbol rewrite).\n"
        "- Length must be 20-220 characters.\n"
        "- If valid quote cannot be produced, DO NOT output that claim.\n"
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
        "LOW-VALUE CHUNK HANDLING:\n"
        "- If the chunk contains only tables of contents, page headers/footers, figure/table\n"
        "  captions without scientific content, or acknowledgment/funding boilerplate,\n"
        "  output an EMPTY claims array.\n"
        "- Do NOT force-extract claims from low-information-density text.\n"
    )
    default_user = (
        f"Allowed step types: {step_ids}\n"
        f"Allowed claim kinds: {kind_ids}\n"
        f"Max claims: {max_claims}\n\n"
        "Chunk text:\n"
        f"{text}\n\n"
        "Output JSON schema:\n"
        '{ "claims": [ {"text":"...", "evidence_quote":"...", "step_type":"Background", "claim_kinds":["Definition"], "confidence":0.0} ] }'
    )
    system = str(prompts.get("phase1_chunk_claim_extract_system") or "").strip() or default_system
    user_t = str(prompts.get("phase1_chunk_claim_extract_user_template") or "").strip()
    if user_t:
        user = _render_template(
            user_t,
            {
                "step_ids": step_ids,
                "kind_ids": kind_ids,
                "max_claims": max_claims,
                "chunk_text": text,
            },
        )
    else:
        user = default_user
    from app.llm.client import call_validated_json
    from app.llm.schemas import ChunkClaimsResponse

    try:
        validated = call_validated_json(system, user, ChunkClaimsResponse)
        out = validated.model_dump()
    except Exception:
        out = call_json(system, user)
    rows = out.get("claims") or []
    if not isinstance(rows, list):
        return []
    clean = []
    step_set = set(step_ids)
    kind_set = set(kind_ids)
    for row in rows[: max(1, max_claims)]:
        if not isinstance(row, dict):
            continue
        text_v = str(row.get("text") or "").strip()
        evidence_quote = str(row.get("evidence_quote") or "").strip()
        step_type = str(row.get("step_type") or "").strip()
        if not text_v or step_type not in step_set or not evidence_quote:
            continue
        kinds = []
        for k in row.get("claim_kinds") or []:
            kk = str(k or "").strip()
            if kk and kk in kind_set and kk not in kinds:
                kinds.append(kk)
        try:
            conf = float(row.get("confidence") or 0.5)
        except Exception:
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        span_start, span_end, match_mode = find_span_by_quote(evidence_quote, text)
        if span_start < 0 or span_end <= span_start:
            continue
        clean.append({
            "text": text_v,
            "evidence_quote": evidence_quote,
            "step_type": step_type,
            "kinds": kinds,
            "confidence": conf,
            "span_start": span_start,
            "span_end": span_end,
            "match_mode": match_mode,
        })
    return clean


def _validate_batch_claims_for_chunk(
    *,
    raw_claims: list[dict[str, Any]],
    chunk_text: str,
    step_set: set[str],
    kind_set: set[str],
    max_claims: int,
) -> tuple[list[dict[str, Any]], int]:
    """Validate claims from a batch response against a specific chunk's text.

    Returns (valid_claims, quote_mismatch_count).
    """
    clean: list[dict[str, Any]] = []
    quote_mismatch = 0
    for row in raw_claims[: max(1, max_claims)]:
        if not isinstance(row, dict):
            continue
        text_v = str(row.get("text") or "").strip()
        evidence_quote = str(row.get("evidence_quote") or "").strip()
        step_type = str(row.get("step_type") or "").strip()
        if not text_v or step_type not in step_set or not evidence_quote:
            continue
        kinds: list[str] = []
        for k in row.get("claim_kinds") or []:
            kk = str(k or "").strip()
            if kk and kk in kind_set and kk not in kinds:
                kinds.append(kk)
        try:
            conf = float(row.get("confidence") or 0.5)
        except Exception:
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        span_start, span_end, match_mode = find_span_by_quote(evidence_quote, chunk_text)
        if span_start < 0 or span_end <= span_start:
            quote_mismatch += 1
            continue
        clean.append({
            "text": text_v,
            "evidence_quote": evidence_quote,
            "step_type": step_type,
            "kinds": kinds,
            "confidence": conf,
            "span_start": span_start,
            "span_end": span_end,
            "match_mode": match_mode,
        })
    return clean, quote_mismatch


def _extract_claims_from_chunks_batch_llm(
    *,
    chunks: list[dict[str, str]],
    step_ids: list[str],
    kind_ids: list[str],
    max_claims_per_chunk: int,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Extract claims from multiple chunks in a single LLM call.

    Args:
        chunks: List of {"chunk_id": ..., "text": ...} dicts.
        step_ids: Allowed logic step types.
        kind_ids: Allowed claim kinds.
        max_claims_per_chunk: Max claims per chunk.
        schema: Active schema dict.

    Returns:
        {
            "results": {chunk_id: list[dict]},  # validated claims per chunk
            "failed_chunk_ids": list[str],       # chunks needing single-retry
            "quote_mismatch_count": int,
            "unknown_chunk_id_count": int,
        }
    """
    from app.llm.client import call_json, call_validated_json
    from app.llm.schemas import ChunkClaimsBatchResponse

    rules = schema.get("rules") or {}
    prompts = schema.get("prompts") or {}
    chunk_chars_max = max(200, min(12000, _rule_int(rules, "phase1_chunk_chars_max", 1800)))

    # Prepare chunk texts (truncated)
    input_chunks: list[dict[str, str]] = []
    input_chunk_ids: set[str] = set()
    for c in chunks:
        cid = str(c.get("chunk_id") or "").strip()
        text = (c.get("text") or "").strip()
        if not cid or not text:
            continue
        if len(text) > chunk_chars_max:
            text = _truncate_to_sentence_boundary(text, chunk_chars_max)
        input_chunks.append({"chunk_id": cid, "text": text})
        input_chunk_ids.add(cid)

    if not input_chunks:
        return {"results": {}, "failed_chunk_ids": [], "quote_mismatch_count": 0, "unknown_chunk_id_count": 0}

    # Build prompt
    chunks_block = "\n\n".join(
        f"--- CHUNK [{c['chunk_id']}] ---\n{c['text']}" for c in input_chunks
    )
    default_system = (
        "Extract atomic claims from MULTIPLE paper chunks. Return STRICT JSON only.\n"
        "\n"
        "GROUNDING:\n"
        "- Each claim must be directly supported by its chunk text.\n"
        "- Do not invent information outside the chunk.\n"
        "\n"
        "EVIDENCE QUOTE (REQUIRED):\n"
        "- evidence_quote must be copied VERBATIM from the chunk text (no paraphrase).\n"
        "- Length must be 20-220 characters.\n"
        "- If valid quote cannot be produced, DO NOT output that claim.\n"
        "\n"
        "SCIENTIFIC VALUE (CRITICAL):\n"
        "- Extract ONLY scientific contributions, methods, findings, and conclusions.\n"
        "- DO NOT extract meta-information (authors, dates, funding, DOIs, etc.).\n"
        "- When encountering pure meta-information chunks, output empty claims array for that chunk.\n"
        "\n"
        "LOW-VALUE CHUNK HANDLING:\n"
        "- If a chunk contains only tables of contents, page headers/footers, figure/table\n"
        "  captions without scientific content, or acknowledgment/funding boilerplate,\n"
        "  output an EMPTY claims array for that chunk.\n"
        "- Do NOT force-extract claims from low-information-density text.\n"
        "\n"
        "OUTPUT FORMAT:\n"
        '{ "chunks": [ {"chunk_id":"c1", "claims": [{"text":"...", "evidence_quote":"...", '
        '"step_type":"Background", "claim_kinds":["Definition"], "confidence":0.8}]} ] }\n'
        "You MUST output one entry per input chunk_id, even if claims is empty."
    )
    default_user = (
        f"Allowed step types: {step_ids}\n"
        f"Allowed claim kinds: {kind_ids}\n"
        f"Max claims per chunk: {max_claims_per_chunk}\n\n"
        f"{chunks_block}\n\n"
        "Output JSON with one entry per chunk_id."
    )
    system = str(prompts.get("phase1_chunk_claim_extract_system") or "").strip() or default_system
    user_t = str(prompts.get("phase1_chunk_claim_batch_user_template") or "").strip()
    if user_t:
        user = _render_template(
            user_t,
            {
                "step_ids": step_ids,
                "kind_ids": kind_ids,
                "max_claims_per_chunk": max_claims_per_chunk,
                "chunks_block": chunks_block,
                "chunk_count": len(input_chunks),
            },
        )
    else:
        user = default_user

    # Call LLM
    try:
        validated = call_validated_json(system, user, ChunkClaimsBatchResponse)
        out = validated.model_dump()
    except Exception:
        try:
            out = call_json(system, user)
        except Exception:
            # Total batch failure
            return {
                "results": {},
                "failed_chunk_ids": list(input_chunk_ids),
                "quote_mismatch_count": 0,
                "unknown_chunk_id_count": 0,
            }

    # Parse and validate per-chunk
    step_set = set(step_ids)
    kind_set = set(kind_ids)
    raw_chunks = out.get("chunks") or []
    if not isinstance(raw_chunks, list):
        return {
            "results": {},
            "failed_chunk_ids": list(input_chunk_ids),
            "quote_mismatch_count": 0,
            "unknown_chunk_id_count": 0,
        }

    results: dict[str, list[dict[str, Any]]] = {}
    total_quote_mismatch = 0
    unknown_chunk_id_count = 0
    seen_chunk_ids: set[str] = set()

    # Build chunk_id -> text lookup
    text_by_id = {c["chunk_id"]: c["text"] for c in input_chunks}

    for entry in raw_chunks:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("chunk_id") or "").strip()
        if not cid:
            continue
        if cid not in input_chunk_ids:
            unknown_chunk_id_count += 1
            continue
        seen_chunk_ids.add(cid)
        raw_claims = entry.get("claims") or []
        if not isinstance(raw_claims, list):
            raw_claims = []
        chunk_text = text_by_id.get(cid, "")
        valid_claims, mismatches = _validate_batch_claims_for_chunk(
            raw_claims=raw_claims,
            chunk_text=chunk_text,
            step_set=step_set,
            kind_set=kind_set,
            max_claims=max_claims_per_chunk,
        )
        total_quote_mismatch += mismatches
        # Quality gate: if quote_match_rate < 50% for this chunk, mark as failed
        total_attempted = len([r for r in raw_claims if isinstance(r, dict) and str(r.get("text") or "").strip()])
        if total_attempted > 0 and len(valid_claims) / total_attempted < 0.5:
            # Too many mismatches — fallback to single extraction for this chunk
            continue
        results[cid] = valid_claims

    # Chunks not seen in output → need single-retry
    failed_chunk_ids = [cid for cid in input_chunk_ids if cid not in results]

    return {
        "results": results,
        "failed_chunk_ids": failed_chunk_ids,
        "quote_mismatch_count": total_quote_mismatch,
        "unknown_chunk_id_count": unknown_chunk_id_count,
    }


def _default_claim_extractor(
    *,
    doc: DocumentIR,
    paper_id: str,
    schema: dict[str, Any],
    step_order: list[str],
    logic: dict[str, Any],
) -> dict[str, Any]:
    rules = schema.get("rules") or {}
    max_chunks = int(rules.get("phase1_claim_chunks_max") or 36)
    max_claims_per_chunk = int(rules.get("phase1_claims_per_chunk_max") or 3)
    max_chunks = max(1, min(9999, max_chunks))
    max_claims_per_chunk = max(1, min(8, max_claims_per_chunk))
    step_ids = step_order or _enabled_step_ids(schema)
    kind_ids = _enabled_kind_ids(schema)

    batch_size = max(1, min(12, int(rules.get("phase1_claim_batch_size") or 6)))

    candidates: list[dict[str, Any]] = []
    chunks = _priority_chunks(doc, logic=logic, max_chunks=max_chunks, rules=rules)
    chunk_fail_count = 0
    worker_count = max(1, int(rules.get("phase1_claim_worker_count") or 3))

    # Stats for batch extraction
    batch_quote_mismatch_count = 0
    batch_unknown_chunk_id_count = 0
    batch_fallback_chunk_count = 0

    # Prepare valid chunk list
    valid_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        chunk_text = str(chunk.get("text") or "")
        if chunk_id and chunk_text.strip():
            valid_chunks.append({"chunk_id": chunk_id, "text": chunk_text, "_idx": len(valid_chunks)})

    # Group into batches
    chunk_batches: list[list[dict[str, Any]]] = []
    for i in range(0, len(valid_chunks), batch_size):
        chunk_batches.append(valid_chunks[i : i + batch_size])

    def _process_batch(batch: list[dict[str, Any]]) -> dict[str, Any]:
        """Process a single batch with tiered fallback. Returns per-chunk results."""
        batch_input = [{"chunk_id": c["chunk_id"], "text": c["text"]} for c in batch]

        # Try full batch
        result = _extract_claims_from_chunks_batch_llm(
            chunks=batch_input,
            step_ids=step_ids,
            kind_ids=kind_ids,
            max_claims_per_chunk=max_claims_per_chunk,
            schema=schema,
        )

        failed_ids = set(result.get("failed_chunk_ids") or [])
        per_chunk = dict(result.get("results") or {})
        stats = {
            "quote_mismatch": result.get("quote_mismatch_count", 0),
            "unknown_chunk_id": result.get("unknown_chunk_id_count", 0),
            "fallback_chunks": 0,
        }

        if not failed_ids:
            return {"per_chunk": per_chunk, "stats": stats}

        # Tiered fallback: try half-batch for failed chunks
        failed_batch = [c for c in batch if c["chunk_id"] in failed_ids]
        if len(failed_batch) > 1:
            half = max(1, len(failed_batch) // 2)
            for sub_start in range(0, len(failed_batch), half):
                sub_batch = failed_batch[sub_start : sub_start + half]
                sub_input = [{"chunk_id": c["chunk_id"], "text": c["text"]} for c in sub_batch]
                sub_result = _extract_claims_from_chunks_batch_llm(
                    chunks=sub_input,
                    step_ids=step_ids,
                    kind_ids=kind_ids,
                    max_claims_per_chunk=max_claims_per_chunk,
                    schema=schema,
                )
                for cid, claims in (sub_result.get("results") or {}).items():
                    per_chunk[cid] = claims
                    failed_ids.discard(cid)
                stats["quote_mismatch"] += sub_result.get("quote_mismatch_count", 0)
                stats["unknown_chunk_id"] += sub_result.get("unknown_chunk_id_count", 0)

        # Final fallback: single-chunk extraction for remaining failures
        for c in batch:
            if c["chunk_id"] not in failed_ids:
                continue
            try:
                rows = _extract_claims_from_chunk_llm(
                    chunk_text=c["text"],
                    step_ids=step_ids,
                    kind_ids=kind_ids,
                    max_claims=max_claims_per_chunk,
                    schema=schema,
                )
                per_chunk[c["chunk_id"]] = rows
                stats["fallback_chunks"] += 1
            except Exception:
                stats["fallback_chunks"] += 1

        return {"per_chunk": per_chunk, "stats": stats}

    # Execute batches with parallel workers
    from concurrent.futures import ThreadPoolExecutor

    from app.settings import settings as app_settings

    max_workers = min(app_settings.phase1_chunk_claim_max_workers, len(chunk_batches))
    max_workers = max(1, max_workers)

    batch_results: list[tuple[int, dict[str, Any]]] = []
    if max_workers == 1 or len(chunk_batches) <= 1:
        # Sequential path
        for bi, batch in enumerate(chunk_batches):
            br = _process_batch(batch)
            batch_results.append((bi, br))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_process_batch, b): bi for bi, b in enumerate(chunk_batches)}
            for future in futures:
                bi = futures[future]
                try:
                    br = future.result()
                except Exception:
                    br = {"per_chunk": {}, "stats": {"quote_mismatch": 0, "unknown_chunk_id": 0, "fallback_chunks": 0}}
                batch_results.append((bi, br))

    # Merge results in deterministic order
    batch_results.sort(key=lambda x: x[0])
    chunk_idx_map = {c["chunk_id"]: c["_idx"] for c in valid_chunks}

    for _bi, br in batch_results:
        stats = br.get("stats") or {}
        batch_quote_mismatch_count += stats.get("quote_mismatch", 0)
        batch_unknown_chunk_id_count += stats.get("unknown_chunk_id", 0)
        batch_fallback_chunk_count += stats.get("fallback_chunks", 0)
        per_chunk = br.get("per_chunk") or {}
        # Sort by chunk index for deterministic candidate ordering
        sorted_chunks = sorted(per_chunk.items(), key=lambda kv: chunk_idx_map.get(kv[0], 0))
        for cid, rows in sorted_chunks:
            idx = chunk_idx_map.get(cid, 0)
            for r in rows:
                candidates.append(
                    {
                        "text": r["text"],
                        "evidence_quote": str(r.get("evidence_quote") or ""),
                        "confidence": r["confidence"],
                        "step_type": r["step_type"],
                        "kinds": list(r.get("kinds") or []),
                        "origin_chunk_id": cid,
                        "worker_id": f"w{(idx % worker_count) + 1}",
                        "span_start": int(r["span_start"]) if r.get("span_start") is not None else -1,
                        "span_end": int(r["span_end"]) if r.get("span_end") is not None else -1,
                        "match_mode": str(r.get("match_mode") or ""),
                    }
                )

    # Count chunks with no output as failures
    all_output_chunk_ids = set()
    for _bi, br in batch_results:
        all_output_chunk_ids.update((br.get("per_chunk") or {}).keys())
    for c in valid_chunks:
        if c["chunk_id"] not in all_output_chunk_ids:
            chunk_fail_count += 1

    return {
        "candidates": candidates,
        "chunk_total": len(chunks),
        "chunk_fail_count": chunk_fail_count,
        "chunk_extraction_stats": {
            "batch_size": batch_size,
            "batch_count": len(chunk_batches),
            "batch_quote_mismatch_count": batch_quote_mismatch_count,
            "batch_unknown_chunk_id_count": batch_unknown_chunk_id_count,
            "batch_fallback_chunk_count": batch_fallback_chunk_count,
        },
    }


def _observe_semantic_duplicates(
    claims: list[dict[str, Any]],
    *,
    rules: dict[str, Any],
) -> list[dict[str, Any]]:
    """Observation-only: find claim pairs with high embedding similarity. Does NOT merge."""
    threshold = _rule_float(rules, "phase1_dedup_similarity_threshold", 0.92)
    max_claims = _rule_int(rules, "phase1_dedup_max_claims", 200)
    if len(claims) < 2 or len(claims) > max_claims:
        return []
    texts = [str(c.get("text") or "") for c in claims]
    try:
        from app.similarity.embedding import get_embeddings_batch
        embeddings = get_embeddings_batch(texts)
    except Exception:
        logger.debug("Semantic dedup observation skipped: embedding unavailable", exc_info=True)
        return []
    if len(embeddings) != len(texts):
        return []
    # Pairwise cosine similarity (brute force, small N)
    import math
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1e-9
        nb = math.sqrt(sum(x * x for x in b)) or 1e-9
        return dot / (na * nb)

    pairs: list[dict[str, Any]] = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            sim = _cosine(embeddings[i], embeddings[j])
            if sim >= threshold:
                pairs.append({
                    "claim_a_id": str(claims[i].get("canonical_claim_id") or claims[i].get("claim_id") or ""),
                    "claim_b_id": str(claims[j].get("canonical_claim_id") or claims[j].get("claim_id") or ""),
                    "text_a": texts[i][:200],
                    "text_b": texts[j][:200],
                    "similarity": round(sim, 4),
                })
    return pairs


def _merge_claim_candidates(
    *,
    claims: list[dict[str, Any]],
    paper_id: str,
    doi: str | None,
    step_order: list[str],
) -> list[dict[str, Any]]:
    step_rank = {s: i for i, s in enumerate(step_order)}
    buckets: dict[str, dict[str, Any]] = {}
    for c in claims:
        text = _norm_text(str(c.get("text") or ""))
        if not text:
            continue
        step_type = str(c.get("step_type") or "").strip()
        if not step_type:
            continue
        key_seed = f"{step_type.lower()}\0{text.lower()}"
        bucket_key = hashlib.sha256(key_seed.encode("utf-8", errors="ignore")).hexdigest()[:24]
        if bucket_key not in buckets:
            buckets[bucket_key] = {
                "texts": [],
                "step_type": step_type,
                "kinds": set(),
                "origin_chunk_ids": [],
                "worker_ids": set(),
                "confidence_sum": 0.0,
                "confidence_n": 0,
                "span_candidates": [],  # track (text, span_start, span_end, match_mode, evidence_quote)
            }
        b = buckets[bucket_key]
        b["texts"].append(text)
        b["span_candidates"].append((
            c.get("text", ""),  # original text (not normalized)
            int(c.get("span_start", -1)),
            int(c.get("span_end", -1)),
            str(c.get("match_mode") or ""),
            str(c.get("evidence_quote") or ""),
        ))
        b["kinds"].update(str(x).strip() for x in (c.get("kinds") or []) if str(x).strip())
        cid = str(c.get("origin_chunk_id") or "").strip()
        if cid and cid not in b["origin_chunk_ids"]:
            b["origin_chunk_ids"].append(cid)
        wid = str(c.get("worker_id") or "").strip()
        if wid:
            b["worker_ids"].add(wid)
        try:
            conf = float(c.get("confidence") or 0.5)
        except Exception:
            conf = 0.5
        b["confidence_sum"] += max(0.0, min(1.0, conf))
        b["confidence_n"] += 1

    out = []
    doi_s = str(doi or "").strip().lower()
    for bucket in buckets.values():
        texts = list(bucket["texts"])
        texts.sort(key=len, reverse=True)
        canonical_text = texts[0] if texts else ""

        # Find the span corresponding to the canonical text from span_candidates
        canonical_span_start, canonical_span_end = -1, -1
        canonical_match_mode = "none"
        canonical_evidence_quote = ""
        for cand_text, cand_start, cand_end, cand_mode, cand_quote in bucket.get("span_candidates") or []:
            if cand_text == canonical_text and cand_start >= 0 and cand_end > cand_start:
                canonical_span_start, canonical_span_end = cand_start, cand_end
                canonical_match_mode = str(cand_mode or "none")
                canonical_evidence_quote = str(cand_quote or "")
                break

        # Fallback: pick any valid span if canonical text has no span
        if canonical_span_start < 0:
            for _cand_text, cand_start, cand_end, cand_mode, cand_quote in bucket.get("span_candidates") or []:
                if cand_start >= 0 and cand_end > cand_start:
                    canonical_span_start, canonical_span_end = cand_start, cand_end
                    canonical_match_mode = str(cand_mode or "none")
                    canonical_evidence_quote = str(cand_quote or "")
                    break

        claim_key = _claim_key_for(doi=doi_s, paper_id=paper_id, text=canonical_text)
        claim_id = _claim_id_for(paper_id=paper_id, claim_key=claim_key)
        n = max(1, int(bucket["confidence_n"]))
        out.append(
            {
                "canonical_claim_id": claim_id,
                "claim_id": claim_id,
                "claim_key": claim_key,
                "text": canonical_text,
                "variants": texts,
                "step_type": str(bucket["step_type"]),
                "kinds": sorted(bucket["kinds"]),
                "origin_chunk_ids": list(bucket["origin_chunk_ids"]),
                "origin_chunk_id": str(bucket["origin_chunk_ids"][0]) if bucket["origin_chunk_ids"] else "",
                "worker_ids": sorted(bucket["worker_ids"]),
                "confidence": float(bucket["confidence_sum"]) / float(n),
                "span_start": canonical_span_start,
                "span_end": canonical_span_end,
                "match_mode": canonical_match_mode,
                "evidence_quote": canonical_evidence_quote,
            }
        )

    out.sort(
        key=lambda x: (
            int(step_rank.get(str(x.get("step_type") or ""), 10_000)),
            -float(x.get("confidence") or 0.0),
            str(x.get("claim_key") or ""),
        )
    )

    # P1 Fix: Cross-step claim_id collision resolution.
    # bucket_key includes step_type, but claim_id does not. Same canonical text in
    # different steps lands in separate buckets but produces the same claim_id.
    # Strategy: keep the highest-priority step's record, but merge evidence
    # (kinds, origin_chunk_ids, worker_ids) from lower-priority duplicates so no
    # evidence is silently discarded.
    primary: dict[str, dict[str, Any]] = {}  # claim_id → kept item (highest priority)
    for item in out:
        claim_id = str(item.get("claim_id") or item.get("canonical_claim_id") or "").strip()
        if not claim_id:
            continue
        if claim_id not in primary:
            primary[claim_id] = dict(item)
            # Promote kinds/origin_chunk_ids to mutable for later merging
            primary[claim_id]["kinds"] = list(item.get("kinds") or [])
            primary[claim_id]["origin_chunk_ids"] = list(item.get("origin_chunk_ids") or [])
            primary[claim_id]["worker_ids"] = sorted(item.get("worker_ids") or [])
        else:
            kept = primary[claim_id]
            logger.warning(
                "Phase1 merge: cross-step claim_id collision claim_id=%s "
                "discarded_step_type=%s (keeping step_type=%s); merging evidence",
                claim_id,
                str(item.get("step_type") or "").strip(),
                str(kept.get("step_type") or "").strip(),
            )
            # Merge evidence from the discarded duplicate into the kept item
            for k in list(item.get("kinds") or []):
                if k not in kept["kinds"]:
                    kept["kinds"].append(k)
            for cid in list(item.get("origin_chunk_ids") or []):
                if cid not in kept["origin_chunk_ids"]:
                    kept["origin_chunk_ids"].append(cid)
            wids = set(kept.get("worker_ids") or []) | set(item.get("worker_ids") or [])
            kept["worker_ids"] = sorted(wids)
            # Keep first origin_chunk_id consistent
            if kept["origin_chunk_ids"]:
                kept["origin_chunk_id"] = kept["origin_chunk_ids"][0]

    # Re-apply original sort order (primary dict preserves insertion order = priority order)
    deduped_out = list(primary.values())
    # Re-sort items that have no claim_id (edge case: pass-through)
    no_id = [item for item in out if not str(item.get("claim_id") or item.get("canonical_claim_id") or "").strip()]
    return deduped_out + no_id


def _tokens(s: str, *, stop_tokens: set[str] | None = None) -> list[str]:
    stop = stop_tokens if stop_tokens is not None else _STOP_TOKENS
    toks = _TOKEN_RE.findall((s or "").lower())
    out = []
    for t in toks:
        if re.fullmatch(r"[\u4e00-\u9fff]+", t) and len(t) > 2:
            out.extend(list(t))
        else:
            out.append(t)
    return [t for t in out if t and t not in stop]


def _preferred_kinds_for_step(step: str) -> list[str]:
    sid = str(step or "").strip().lower()
    if sid == "background":
        return ["Definition", "Scope", "Taxonomy", "Gap"]
    if sid == "problem":
        return ["Gap", "Assumption", "Comparison", "Definition"]
    if sid == "method":
        return ["Method", "Assumption", "Comparison", "Result"]
    if sid == "experiment":
        return ["Method", "Result", "Comparison", "Assumption"]
    if sid == "result":
        return ["Result", "Comparison", "Method"]
    if sid == "conclusion":
        return ["Conclusion", "Limitation", "FutureWork", "Gap", "Result"]
    if sid == "scope":
        return ["Scope", "Definition", "Taxonomy"]
    if sid == "taxonomy":
        return ["Taxonomy", "Definition", "Comparison", "Scope"]
    if sid == "comparison":
        return ["Comparison", "Result", "Critique", "Method"]
    if sid == "gap":
        return ["Gap", "Limitation", "FutureWork", "Critique"]
    return ["Result", "Comparison", "Method", "Definition", "Gap"]


def _auto_step_kind_map(
    *,
    critical_steps: list[str],
    critical_kinds: list[str],
    max_kinds_per_step: int,
) -> dict[str, list[str]]:
    kind_set = {str(x).strip() for x in critical_kinds if str(x).strip()}
    out: dict[str, list[str]] = {}
    cap = max(1, min(6, int(max_kinds_per_step)))
    for step in critical_steps:
        picked: list[str] = []
        for kind in _preferred_kinds_for_step(step):
            if kind in kind_set and kind not in picked:
                picked.append(kind)
            if len(picked) >= cap:
                break
        if not picked:
            for kind in critical_kinds:
                kk = str(kind).strip()
                if kk and kk not in picked:
                    picked.append(kk)
                if len(picked) >= cap:
                    break
        if picked:
            out[str(step)] = picked
    return out


def _critical_slot_spec(step_order: list[str], schema: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    steps_all = [str(s).strip() for s in (step_order or _enabled_step_ids(schema)) if str(s).strip()]
    steps_set = set(steps_all)
    kinds_all = _enabled_kind_ids(schema)
    kinds_set = set(kinds_all)

    step_kind_map_raw = rules.get("phase2_critical_step_kind_map")
    critical_step_kind_map: dict[str, list[str]] = {}
    if isinstance(step_kind_map_raw, dict):
        indexed: dict[str, list[str]] = {}
        for raw_step, raw_kinds in step_kind_map_raw.items():
            step = str(raw_step or "").strip()
            if not step or step not in steps_set:
                continue
            if not isinstance(raw_kinds, list):
                continue
            kinds: list[str] = []
            for raw_kind in raw_kinds:
                kind = str(raw_kind or "").strip()
                if not kind or kind not in kinds_set or kind in kinds:
                    continue
                kinds.append(kind)
            if kinds:
                indexed[step] = kinds
        for step in steps_all:
            kinds = indexed.get(step)
            if kinds:
                critical_step_kind_map[step] = kinds
    if critical_step_kind_map:
        slot_mode = "step_kind_map"
        critical_steps = list(critical_step_kind_map.keys())
        critical_kinds: list[str] = []
        for step in critical_steps:
            for kind in critical_step_kind_map.get(step, []):
                if kind not in critical_kinds:
                    critical_kinds.append(kind)
        slots = [f"{step}|{kind}" for step in critical_steps for kind in critical_step_kind_map.get(step, [])]
        return {
            "slot_mode": slot_mode,
            "critical_steps": critical_steps,
            "critical_kinds": critical_kinds,
            "critical_slots": slots,
            "critical_step_kind_map": critical_step_kind_map,
        }

    req_steps = [str(x).strip() for x in (rules.get("phase2_critical_steps") or []) if str(x).strip()]
    critical_steps = [x for x in req_steps if x in steps_set]
    if not critical_steps:
        critical_steps = list(steps_all)

    req_kinds = [str(x).strip() for x in (rules.get("phase2_critical_kinds") or []) if str(x).strip()]
    critical_kinds = [x for x in req_kinds if x in kinds_set]
    auto_map_enabled = _rule_bool(rules, "phase2_auto_step_kind_map_enabled", True)
    auto_map_trigger_slots = max(1, _rule_int(rules, "phase2_auto_step_kind_map_trigger_slots", 12))
    auto_map_max_kinds = max(1, _rule_int(rules, "phase2_auto_step_kind_map_max_kinds_per_step", 1))
    cartesian_slots = len(critical_steps) * len(critical_kinds)
    if auto_map_enabled and critical_steps and critical_kinds and cartesian_slots >= auto_map_trigger_slots:
        auto_map = _auto_step_kind_map(
            critical_steps=critical_steps,
            critical_kinds=critical_kinds,
            max_kinds_per_step=auto_map_max_kinds,
        )
        if auto_map:
            slot_mode = "step_kind_map_auto"
            slots = [f"{s}|{k}" for s in critical_steps for k in auto_map.get(s, [])]
            auto_kinds: list[str] = []
            for s in critical_steps:
                for k in auto_map.get(s, []):
                    if k not in auto_kinds:
                        auto_kinds.append(k)
            return {
                "slot_mode": slot_mode,
                "critical_steps": critical_steps,
                "critical_kinds": auto_kinds,
                "critical_slots": slots,
                "critical_step_kind_map": auto_map,
            }
    slot_mode = "step_kind" if bool(critical_kinds) else "step_only"
    if slot_mode == "step_kind":
        slots = [f"{s}|{k}" for s in critical_steps for k in critical_kinds]
    else:
        slots = [f"{s}|*" for s in critical_steps]

    return {
        "slot_mode": slot_mode,
        "critical_steps": critical_steps,
        "critical_kinds": critical_kinds,
        "critical_slots": slots,
        "critical_step_kind_map": {},
    }


def _completeness_stats(validated: list[dict[str, Any]], step_order: list[str], schema: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    spec = _critical_slot_spec(step_order=step_order, schema=schema, rules=rules)
    slot_mode = str(spec.get("slot_mode") or "step_only")
    critical_steps = list(spec.get("critical_steps") or [])
    critical_kinds = list(spec.get("critical_kinds") or [])
    critical_slots = list(spec.get("critical_slots") or [])
    critical_step_kind_map = dict(spec.get("critical_step_kind_map") or {})
    critical_step_set = set(critical_steps)
    critical_kind_set = set(critical_kinds)

    covered_slots: set[str] = set()
    slot_claim_counts: dict[str, int] = {}
    step_claim_counts: dict[str, int] = {}
    for claim in validated:
        step = str(claim.get("step_type") or "").strip()
        if not step or step not in critical_step_set:
            continue
        step_claim_counts[step] = step_claim_counts.get(step, 0) + 1
        if slot_mode in {"step_kind_map", "step_kind_map_auto"}:
            kinds = [str(x).strip() for x in (claim.get("kinds") or []) if str(x).strip()]
            step_kinds = set(str(x).strip() for x in (critical_step_kind_map.get(step) or []) if str(x).strip())
            for kind in kinds:
                if kind not in step_kinds:
                    continue
                slot = f"{step}|{kind}"
                covered_slots.add(slot)
                slot_claim_counts[slot] = slot_claim_counts.get(slot, 0) + 1
        elif slot_mode == "step_kind":
            kinds = [str(x).strip() for x in (claim.get("kinds") or []) if str(x).strip()]
            for kind in kinds:
                if kind not in critical_kind_set:
                    continue
                slot = f"{step}|{kind}"
                covered_slots.add(slot)
                slot_claim_counts[slot] = slot_claim_counts.get(slot, 0) + 1
        else:
            slot = f"{step}|*"
            covered_slots.add(slot)
            slot_claim_counts[slot] = slot_claim_counts.get(slot, 0) + 1

    missing_slots = [slot for slot in critical_slots if slot not in covered_slots]
    coverage = float(len(covered_slots)) / float(max(1, len(critical_slots)))
    return {
        "critical_slot_mode": slot_mode,
        "critical_steps": critical_steps,
        "critical_kinds": critical_kinds,
        "critical_step_kind_map": critical_step_kind_map,
        "critical_slots_total": len(critical_slots),
        "critical_slots_covered": len(covered_slots),
        "critical_slot_coverage": coverage,
        "missing_critical_slots": missing_slots,
        "slot_claim_counts": slot_claim_counts,
        "step_claim_counts": step_claim_counts,
    }


def _claim_polarity(text: str, rules: dict[str, Any]) -> int:
    s = _norm_text(text).lower()
    if not s:
        return 0
    pos_terms_en = set(_rule_str_list(rules, "phase2_conflict_positive_terms_en")) or _POLARITY_POS_TOKENS
    neg_terms_en = set(_rule_str_list(rules, "phase2_conflict_negative_terms_en")) or _POLARITY_NEG_TOKENS
    pos_terms_zh = tuple(_rule_str_list(rules, "phase2_conflict_positive_terms_zh")) or _POLARITY_POS_ZH
    neg_terms_zh = tuple(_rule_str_list(rules, "phase2_conflict_negative_terms_zh")) or _POLARITY_NEG_ZH
    toks = _tokens(s, stop_tokens=_effective_stop_tokens(rules))
    pos = sum(1 for t in toks if t in pos_terms_en)
    neg = sum(1 for t in toks if t in neg_terms_en)
    pos += sum(1 for h in pos_terms_zh if h in s)
    neg += sum(1 for h in neg_terms_zh if h in s)
    if pos == 0 and neg == 0:
        return 0
    if pos >= neg + 1:
        return 1
    if neg >= pos + 1:
        return -1
    return 0


def _claim_topic_tokens(text: str, rules: dict[str, Any]) -> set[str]:
    s = _norm_text(text).lower()
    out: set[str] = set()
    pos_terms_en = set(_rule_str_list(rules, "phase2_conflict_positive_terms_en")) or _POLARITY_POS_TOKENS
    neg_terms_en = set(_rule_str_list(rules, "phase2_conflict_negative_terms_en")) or _POLARITY_NEG_TOKENS
    polarity_tokens = pos_terms_en | neg_terms_en
    stop_tokens = _effective_stop_tokens(rules)
    for t in _tokens(s, stop_tokens=stop_tokens):
        if t in stop_tokens or t in polarity_tokens:
            continue
        if len(t) == 1 and not re.fullmatch(r"[\u4e00-\u9fff]", t):
            continue
        out.add(t)
    return out


def _conflict_stats_lexical(validated: list[dict[str, Any]], rules: dict[str, Any]) -> dict[str, Any]:
    max_samples = max(1, min(100, _rule_int(rules, "phase2_conflict_samples_max", 8)))
    shared_tokens_min = max(1, min(10, _rule_int(rules, "phase2_conflict_shared_tokens_min", 2)))
    claims = [c for c in validated if str(c.get("text") or "").strip() and str(c.get("step_type") or "").strip()]
    comparable_pairs = 0
    conflict_pairs = 0
    samples: list[dict[str, Any]] = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            a = claims[i]
            b = claims[j]
            step_a = str(a.get("step_type") or "").strip()
            step_b = str(b.get("step_type") or "").strip()
            if not step_a or step_a != step_b:
                continue
            toks_a = _claim_topic_tokens(str(a.get("text") or ""), rules=rules)
            toks_b = _claim_topic_tokens(str(b.get("text") or ""), rules=rules)
            shared = sorted(toks_a & toks_b)
            if len(shared) < shared_tokens_min:
                continue
            pol_a = _claim_polarity(str(a.get("text") or ""), rules=rules)
            pol_b = _claim_polarity(str(b.get("text") or ""), rules=rules)
            if pol_a == 0 or pol_b == 0:
                continue
            comparable_pairs += 1
            if pol_a * pol_b < 0:
                conflict_pairs += 1
                if len(samples) < max_samples:
                    samples.append(
                        {
                            "claim_id_a": str(a.get("claim_id") or ""),
                            "claim_id_b": str(b.get("claim_id") or ""),
                            "step_type": step_a,
                            "shared_tokens": shared[:12],
                            "text_a": str(a.get("text") or ""),
                            "text_b": str(b.get("text") or ""),
                        }
                    )
    rate = float(conflict_pairs) / float(max(1, comparable_pairs))
    return {
        "comparable_pairs": comparable_pairs,
        "conflict_pairs": conflict_pairs,
        "conflict_rate": rate,
        "conflict_samples": samples,
        "shared_tokens_min": shared_tokens_min,
        "conflict_mode_used": "lexical",
        "conflict_candidate_pairs": comparable_pairs,
        "conflict_semantic_judged": 0,
        "conflict_semantic_coverage_ratio": 0.0,
        "conflict_semantic_insufficient_pairs": 0,
        "conflict_semantic_insufficient_ratio": 0.0,
        "conflict_semantic_missing_pairs": 0,
        "conflict_semantic_unknown_pair_rows": 0,
        "conflict_semantic_threshold": max(0.0, min(1.0, _rule_float(rules, "phase2_conflict_semantic_threshold", 0.75))),
        "conflict_semantic_fallback": False,
        "conflict_semantic_fallback_reason": "",
    }


def _semantic_conflict_candidate_pairs(
    *,
    validated: list[dict[str, Any]],
    rules: dict[str, Any],
    mode: str,
) -> list[dict[str, Any]]:
    shared_tokens_min = max(1, min(10, _rule_int(rules, "phase2_conflict_shared_tokens_min", 2)))
    max_pairs = max(1, min(2000, _rule_int(rules, "phase2_conflict_candidate_max_pairs", 120)))
    claims = [c for c in validated if str(c.get("text") or "").strip() and str(c.get("step_type") or "").strip()]
    out: list[dict[str, Any]] = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            a = claims[i]
            b = claims[j]
            step_a = str(a.get("step_type") or "").strip()
            step_b = str(b.get("step_type") or "").strip()
            if not step_a or step_a != step_b:
                continue
            toks_a = _claim_topic_tokens(str(a.get("text") or ""), rules=rules)
            toks_b = _claim_topic_tokens(str(b.get("text") or ""), rules=rules)
            shared = sorted(toks_a & toks_b)
            if mode == "hybrid" and len(shared) < shared_tokens_min:
                continue
            out.append(
                {
                    "pair_id": f"p{i}_{j}",
                    "step_type": step_a,
                    "claim_id_a": str(a.get("claim_id") or ""),
                    "claim_id_b": str(b.get("claim_id") or ""),
                    "text_a": str(a.get("text") or ""),
                    "text_b": str(b.get("text") or ""),
                    "kinds_a": list(a.get("kinds") or []),
                    "kinds_b": list(b.get("kinds") or []),
                    "shared_tokens": shared[:18],
                }
            )
            if len(out) >= max_pairs:
                return out
    return out


def _conflict_stats_semantic(
    *,
    validated: list[dict[str, Any]],
    rules: dict[str, Any],
    schema: dict[str, Any] | None,
    mode: str,
) -> dict[str, Any]:
    max_samples = max(1, min(100, _rule_int(rules, "phase2_conflict_samples_max", 8)))
    shared_tokens_min = max(1, min(10, _rule_int(rules, "phase2_conflict_shared_tokens_min", 2)))
    threshold = max(0.0, min(1.0, _rule_float(rules, "phase2_conflict_semantic_threshold", 0.75)))
    candidates = _semantic_conflict_candidate_pairs(validated=validated, rules=rules, mode=mode)
    comparable_pairs = len(candidates)
    if comparable_pairs <= 0:
        return {
            "comparable_pairs": 0,
            "conflict_pairs": 0,
            "conflict_rate": 0.0,
            "conflict_samples": [],
            "shared_tokens_min": shared_tokens_min,
            "conflict_mode_used": mode,
            "conflict_candidate_pairs": 0,
            "conflict_semantic_judged": 0,
            "conflict_semantic_coverage_ratio": 0.0,
            "conflict_semantic_insufficient_pairs": 0,
            "conflict_semantic_insufficient_ratio": 0.0,
            "conflict_semantic_missing_pairs": 0,
            "conflict_semantic_unknown_pair_rows": 0,
            "conflict_semantic_threshold": threshold,
            "conflict_semantic_fallback": False,
            "conflict_semantic_fallback_reason": "",
        }

    judge_input = [
        {
            "pair_id": str(x.get("pair_id") or ""),
            "step_type": str(x.get("step_type") or ""),
            "claim_a": str(x.get("text_a") or ""),
            "claim_b": str(x.get("text_b") or ""),
            "kinds_a": list(x.get("kinds_a") or []),
            "kinds_b": list(x.get("kinds_b") or []),
            "shared_tokens": list(x.get("shared_tokens") or []),
        }
        for x in candidates
    ]

    try:
        from app.llm import conflict_judge

        rows = conflict_judge.judge_conflict_pairs_batch(
            pairs=judge_input,
            schema={
                "rules": dict(rules),
                "prompts": dict((schema or {}).get("prompts") or {}),
            },
        )
    except Exception as exc:
        logger.warning(
            "Conflict semantic fallback triggered: mode=%s candidate_pairs=%d error=%s",
            mode,
            comparable_pairs,
            str(exc),
        )
        fallback = _conflict_stats_lexical(validated=validated, rules=rules)
        fallback["conflict_semantic_fallback"] = True
        fallback["conflict_semantic_fallback_reason"] = str(exc)
        fallback["conflict_semantic_threshold"] = threshold
        fallback["conflict_candidate_pairs"] = comparable_pairs
        fallback["conflict_semantic_judged"] = 0
        fallback["conflict_semantic_coverage_ratio"] = 0.0
        fallback["conflict_semantic_insufficient_pairs"] = comparable_pairs
        fallback["conflict_semantic_insufficient_ratio"] = 1.0 if comparable_pairs > 0 else 0.0
        fallback["conflict_semantic_missing_pairs"] = comparable_pairs
        fallback["conflict_semantic_unknown_pair_rows"] = 0
        return fallback

    # Build candidate pair ID set for validation
    candidate_pair_ids = {str(c.get("pair_id") or "").strip() for c in candidates if str(c.get("pair_id") or "").strip()}

    # Filter and validate judgment rows
    rows_with_pair_id = [
        r for r in rows if isinstance(r, dict) and str(r.get("pair_id") or "").strip()
    ]
    unknown_pair_rows = sum(
        1 for r in rows_with_pair_id
        if str(r.get("pair_id") or "").strip() not in candidate_pair_ids
    )

    # Build judgment map (only for known candidate pairs)
    by_pair_id = {
        str(r.get("pair_id") or "").strip(): r
        for r in rows_with_pair_id
        if str(r.get("pair_id") or "").strip() in candidate_pair_ids
    }

    # Process candidates and collect metrics
    conflict_pairs = 0
    semantic_insufficient_pairs = 0
    samples: list[dict[str, Any]] = []

    for c in candidates:
        pid = str(c.get("pair_id") or "")
        row = by_pair_id.get(pid) or {}

        # Defensive label normalization
        label = str(row.get("label") or "insufficient").strip().lower()
        if label not in {"contradict", "not_conflict", "insufficient"}:
            label = "insufficient"

        # Defensive score normalization
        try:
            score = float(row.get("score") or 0.0)
        except Exception:
            score = 0.0
        score = max(0.0, min(1.0, score))

        # Track insufficient judgments
        if label == "insufficient":
            semantic_insufficient_pairs += 1

        # Identify conflicts
        if label == "contradict" and score >= threshold:
            conflict_pairs += 1
            if len(samples) < max_samples:
                samples.append(
                    {
                        "claim_id_a": str(c.get("claim_id_a") or ""),
                        "claim_id_b": str(c.get("claim_id_b") or ""),
                        "step_type": str(c.get("step_type") or ""),
                        "shared_tokens": list(c.get("shared_tokens") or [])[:12],
                        "text_a": str(c.get("text_a") or ""),
                        "text_b": str(c.get("text_b") or ""),
                        "semantic_label": label,
                        "semantic_score": score,
                        "semantic_reason": str(row.get("reason") or ""),
                    }
                )

    # Calculate comprehensive metrics
    semantic_judged = len(by_pair_id)
    semantic_missing_pairs = max(0, comparable_pairs - semantic_judged)
    semantic_coverage_ratio = float(semantic_judged) / float(max(1, comparable_pairs))
    semantic_insufficient_ratio = float(semantic_insufficient_pairs) / float(max(1, comparable_pairs))

    # Structured logging for observability
    logger.info(
        (
            "Conflict semantic metrics: mode=%s candidate_pairs=%d judged=%d coverage=%.4f "
            "insufficient_pairs=%d insufficient_ratio=%.4f missing_pairs=%d unknown_pair_rows=%d"
        ),
        mode,
        comparable_pairs,
        semantic_judged,
        semantic_coverage_ratio,
        semantic_insufficient_pairs,
        semantic_insufficient_ratio,
        semantic_missing_pairs,
        unknown_pair_rows,
    )

    rate = float(conflict_pairs) / float(max(1, comparable_pairs))
    return {
        "comparable_pairs": comparable_pairs,
        "conflict_pairs": conflict_pairs,
        "conflict_rate": rate,
        "conflict_samples": samples,
        "shared_tokens_min": shared_tokens_min,
        "conflict_mode_used": mode,
        "conflict_candidate_pairs": comparable_pairs,
        "conflict_semantic_judged": semantic_judged,
        "conflict_semantic_coverage_ratio": semantic_coverage_ratio,
        "conflict_semantic_insufficient_pairs": semantic_insufficient_pairs,
        "conflict_semantic_insufficient_ratio": semantic_insufficient_ratio,
        "conflict_semantic_missing_pairs": semantic_missing_pairs,
        "conflict_semantic_unknown_pair_rows": unknown_pair_rows,
        "conflict_semantic_threshold": threshold,
        "conflict_semantic_fallback": False,
        "conflict_semantic_fallback_reason": "",
    }


def _conflict_stats(
    validated: list[dict[str, Any]],
    rules: dict[str, Any],
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode = _rule_choice(rules, "phase2_conflict_mode", ("lexical", "hybrid", "llm"), "lexical")
    if mode == "lexical":
        return _conflict_stats_lexical(validated=validated, rules=rules)
    return _conflict_stats_semantic(validated=validated, rules=rules, schema=schema, mode=mode)


def _collect_origin_chunk_ids(claim: dict[str, Any]) -> list[str]:
    """Gather all origin chunk IDs from a claim (plural list preferred, singular fallback)."""
    ids: list[str] = []
    for cid in claim.get("origin_chunk_ids") or []:
        s = str(cid).strip()
        if s and s not in ids:
            ids.append(s)
    if not ids:
        s = str(claim.get("origin_chunk_id") or "").strip()
        if s:
            ids.append(s)
    return ids


def _attach_targets_from_citations(claims: list[dict[str, Any]], cite_rec: dict[str, Any] | None, schema: dict[str, Any]) -> None:
    rules = schema.get("rules") or {}
    require_target_kinds = {str(x).strip() for x in (rules.get("require_targets_for_kinds") or []) if str(x).strip()}
    targets_max = max(0, min(10, int(rules.get("targets_per_claim_max") or 3)))
    cited_by_chunk: dict[str, list[dict[str, Any]]] = {}
    for cr in (cite_rec or {}).get("cites_resolved") or []:
        pid = str(cr.get("cited_paper_id") or "").strip()
        if not pid:
            continue
        mentions = int(cr.get("total_mentions") or 0)
        for cid in cr.get("evidence_chunk_ids") or []:
            key = str(cid).strip()
            if not key:
                continue
            cited_by_chunk.setdefault(key, []).append({"cited_paper_id": pid, "total_mentions": mentions})

    for claim in claims:
        kinds = {str(k).strip() for k in (claim.get("kinds") or []) if str(k).strip()}
        if not kinds.intersection(require_target_kinds):
            claim["targets_paper_ids"] = []
            continue
        score_by_pid: dict[str, int] = {}
        for cid in claim.get("origin_chunk_ids") or []:
            for item in cited_by_chunk.get(str(cid).strip(), []):
                pid = str(item.get("cited_paper_id") or "").strip()
                if not pid:
                    continue
                score_by_pid[pid] = max(score_by_pid.get(pid, 0), int(item.get("total_mentions") or 0))
        ordered = sorted(score_by_pid.items(), key=lambda kv: kv[1], reverse=True)
        claim["targets_paper_ids"] = [pid for pid, _ in ordered[:targets_max]]


def _quality_tier_from_failures(fail_reasons: list[str], rules: dict[str, Any]) -> dict[str, Any]:
    strategy = _rule_choice(rules, "phase2_quality_tier_strategy", ("a1_fail_count",), "a1_fail_count")
    yellow_max = max(0, min(10, _rule_int(rules, "phase2_quality_tier_yellow_max_failures", 1)))
    red_min = max(1, min(10, _rule_int(rules, "phase2_quality_tier_red_min_failures", 2)))
    if red_min <= yellow_max:
        red_min = yellow_max + 1
    fail_count = len(list(fail_reasons or []))
    if fail_count <= 0:
        tier = "green"
    elif fail_count <= yellow_max:
        tier = "yellow"
    elif fail_count >= red_min:
        tier = "red"
    else:
        tier = "red"
    score = max(0.0, min(1.0, 1.0 - (float(fail_count) / 5.0)))
    return {
        "quality_tier_strategy": strategy,
        "quality_tier": tier,
        "quality_tier_fail_count": fail_count,
        "quality_tier_reasons": list(fail_reasons or []),
        "quality_tier_score": score,
        "quality_tier_yellow_max_failures": yellow_max,
        "quality_tier_red_min_failures": red_min,
    }


def _quality_report(
    *,
    claims_merged: list[dict[str, Any]],
    validated: list[dict[str, Any]],
    judgments: list[dict[str, Any]],
    step_order: list[str],
    logic_steps_coverage_ratio: float | None = None,
    logic_covered_steps: set[str] | None = None,
    schema: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    total = len(claims_merged)
    labels = [str(j.get("support_label") or "").strip().lower() for j in judgments]
    supported = sum(1 for x in labels if x == "supported")
    weak = sum(1 for x in labels if x == "weak")
    unsupported = sum(1 for x in labels if x == "unsupported")
    supported_ratio = float(supported) / float(max(1, total))
    steps_all = [s for s in step_order if s]
    steps_set = set(steps_all)
    validated_steps = {
        st for c in validated
        if (st := str(c.get("step_type") or "").strip()) and st in steps_set
    }
    step_coverage = float(len(validated_steps)) / float(max(1, len(steps_all)))
    # Logic steps coverage: fraction of steps that have a non-empty logic summary.
    # Used by "excellent" bypass rules so that software/theory papers with full
    # logic structure but concentrated claims can still pass quality gates.
    if logic_steps_coverage_ratio is not None:
        try:
            logic_steps_coverage = max(0.0, min(1.0, float(logic_steps_coverage_ratio)))
        except Exception:
            logic_steps_coverage = step_coverage
    else:
        logic_steps_coverage = step_coverage
    logic_covered_steps_set = {
        sid for sid in (logic_covered_steps or set())
        if sid in steps_set
    }
    if not logic_covered_steps_set and logic_steps_coverage >= 1.0:
        logic_covered_steps_set = set(steps_set)
    validated_steps_missing_logic = sorted(validated_steps - logic_covered_steps_set)
    completeness = _completeness_stats(validated=validated, step_order=step_order, schema=schema, rules=rules)
    conflict = _conflict_stats(validated=validated, rules=rules, schema=schema)
    grounding_mode_used = _rule_choice(rules, "phase1_grounding_mode", ("skip", "lexical", "hybrid", "llm"), "skip")
    grounding_semantic_judged = 0
    grounding_lexical_judged = 0
    grounding_fallback_count = 0
    grounding_semantic_coverage_rate = 0.0

    # Gate profile: named defaults for gate thresholds (strict/balanced/recall)
    _GATE_PROFILES: dict[str, dict[str, Any]] = {
        "strict": {
            "phase1_gate_supported_ratio_min": 0.72,
            "phase1_gate_step_coverage_min": 0.55,
            "phase2_gate_critical_slot_coverage_min": 0.65,
            "phase2_gate_conflict_rate_max": 0.20,
            "phase1_gate_semantic_coverage_min": 0.3,
            "phase2_gate_logic_steps_coverage_min": 0.90,
        },
        "balanced": {
            "phase1_gate_supported_ratio_min": 0.50,
            "phase1_gate_step_coverage_min": 0.40,
            "phase2_gate_critical_slot_coverage_min": 0.40,
            "phase2_gate_conflict_rate_max": 1.0,
            "phase1_gate_semantic_coverage_min": 0.0,
            "phase2_gate_logic_steps_coverage_min": 0.83,
        },
        "recall": {
            "phase1_gate_supported_ratio_min": 0.30,
            "phase1_gate_step_coverage_min": 0.25,
            "phase2_gate_critical_slot_coverage_min": 0.20,
            "phase2_gate_conflict_rate_max": 1.0,
            "phase1_gate_semantic_coverage_min": 0.0,
            "phase2_gate_logic_steps_coverage_min": 0.67,
        },
    }
    gate_profile_name = str(rules.get("gate_profile") or "balanced").strip().lower()
    gate_defaults = _GATE_PROFILES.get(gate_profile_name, _GATE_PROFILES["balanced"])

    def _gated_float(key: str, fallback: float) -> float:
        return _rule_float(rules, key, gate_defaults.get(key, fallback))

    def _gated_bool(key: str, fallback: bool) -> bool:
        return _rule_bool(rules, key, fallback)

    min_supported = _gated_float("phase1_gate_supported_ratio_min", 0.5)
    min_coverage = _gated_float("phase1_gate_step_coverage_min", 0.4)
    min_critical = _gated_float("phase2_gate_critical_slot_coverage_min", min_coverage)
    max_conflict = _gated_float("phase2_gate_conflict_rate_max", 1.0)
    min_conflict_comparable_pairs = max(0, _rule_int(rules, "phase2_conflict_gate_min_comparable_pairs", 3))
    min_conflict_pairs = max(0, _rule_int(rules, "phase2_conflict_gate_min_conflict_pairs", 1))
    min_semantic_coverage = _gated_float("phase1_gate_semantic_coverage_min", 0.0)

    critical_slot_bypass_enabled = _rule_bool(rules, "phase2_gate_critical_slot_bypass_excellent", False)
    step_bypass_min_critical_steps_with_claims = max(
        1,
        _rule_int(rules, "phase2_gate_step_bypass_min_critical_steps_with_claims", 2),
    )
    step_bypass_require_non_method_claim = _rule_bool(
        rules,
        "phase2_gate_step_bypass_require_non_method_claim",
        True,
    )

    # P0: optional extension for step_coverage gate bypass.
    # Backward-compatible default is False, so old behavior remains unchanged
    # unless schema explicitly enables this flag.
    step_coverage_bypass_enabled = _rule_bool(
        rules,
        "phase2_gate_step_coverage_bypass_excellent",
        False,
    )
    critical_slot_bypass_supported_min = _rule_float(
        rules,
        "phase2_gate_critical_slot_bypass_supported_min",
        0.95,
    )
    critical_slot_bypass_min_coverage = max(
        0.0,
        min(1.0, _rule_float(rules, "phase2_gate_critical_slot_bypass_min_coverage", 0.35)),
    )
    critical_slot_bypass_min_critical_steps_with_claims = max(
        1,
        _rule_int(rules, "phase2_gate_critical_slot_bypass_min_critical_steps_with_claims", 2),
    )
    critical_slot_bypass_require_result_or_conclusion = _rule_bool(
        rules,
        "phase2_gate_critical_slot_bypass_require_result_or_conclusion",
        True,
    )
    critical_slot_bypass_min_result_like_claims = max(
        1,
        _rule_int(rules, "phase2_gate_critical_slot_bypass_min_result_like_claims", 1),
    )
    critical_slot_bypass_min_result_like_ratio = max(
        0.0,
        min(1.0, _rule_float(rules, "phase2_gate_critical_slot_bypass_min_result_like_ratio", 0.0)),
    )
    base_min_non_method_critical_claims = max(
        0,
        _rule_int(rules, "phase2_gate_base_min_non_method_critical_claims", 0),
    )
    base_min_result_like_claims = max(
        0,
        _rule_int(rules, "phase2_gate_base_min_result_like_claims", 0),
    )
    base_min_result_like_ratio = max(
        0.0,
        min(1.0, _rule_float(rules, "phase2_gate_base_min_result_like_ratio", 0.0)),
    )

    logic_steps_coverage_min = max(
        0.0,
        min(1.0, _gated_float("phase2_gate_logic_steps_coverage_min", 0.83)),
    )
    logic_steps_guard_validated_enabled = _rule_bool(
        rules,
        "phase2_gate_logic_steps_guard_validated",
        True,
    )
    logic_steps_guard_validated_ready = (
        (not logic_steps_guard_validated_enabled)
        or (not validated_steps)
        or (not validated_steps_missing_logic)
    )

    critical_step_claim_counts = dict(completeness.get("step_claim_counts") or {})
    critical_steps_cfg = [
        str(step_id).strip()
        for step_id in (completeness.get("critical_steps") or [])
        if str(step_id).strip()
    ]
    critical_steps_with_claims = sum(
        1 for step_id in critical_steps_cfg if int(critical_step_claim_counts.get(step_id) or 0) > 0
    )
    method_like_steps = [step_id for step_id in critical_steps_cfg if "method" in step_id.lower()]
    non_method_critical_claims = sum(
        int(count or 0)
        for step_id, count in critical_step_claim_counts.items()
        if step_id not in method_like_steps
    )
    result_like_steps = [
        step_id
        for step_id in critical_steps_cfg
        if ("result" in step_id.lower() or "conclusion" in step_id.lower())
    ]
    result_like_claims = sum(
        int(critical_step_claim_counts.get(step_id) or 0)
        for step_id in result_like_steps
    )
    result_like_ratio = float(result_like_claims) / float(max(1, len(validated)))

    # Shared "excellent" eligibility:
    # - supported_ratio high enough
    # - logic step structure reaches configurable threshold
    # - (optional) all validated-claim steps have logic coverage
    # This condition is reused by both bypass paths to keep criteria consistent.
    excellent_bypass_ready = (
        supported_ratio >= critical_slot_bypass_supported_min
        and logic_steps_coverage >= logic_steps_coverage_min
        and logic_steps_guard_validated_ready
    )
    step_coverage_bypass_ready = (
        excellent_bypass_ready
        and critical_steps_with_claims >= step_bypass_min_critical_steps_with_claims
        and (
            (not step_bypass_require_non_method_claim)
            or (not method_like_steps)
            or (non_method_critical_claims > 0)
        )
    )
    critical_slot_bypass_ready = (
        excellent_bypass_ready
        and float(completeness.get("critical_slot_coverage") or 0.0) >= critical_slot_bypass_min_coverage
        and critical_steps_with_claims >= critical_slot_bypass_min_critical_steps_with_claims
        and (
            (not critical_slot_bypass_require_result_or_conclusion)
            or (not result_like_steps)
            or (
                result_like_claims >= critical_slot_bypass_min_result_like_claims
                and result_like_ratio >= critical_slot_bypass_min_result_like_ratio
            )
        )
    )
    critical_slot_bypass_excellent = critical_slot_bypass_enabled and critical_slot_bypass_ready
    step_coverage_bypass_excellent = step_coverage_bypass_enabled and step_coverage_bypass_ready

    comparable_pairs = int(conflict.get("comparable_pairs") or 0)
    conflict_pairs = int(conflict.get("conflict_pairs") or 0)
    conflict_gate_skip_reasons: list[str] = []
    if comparable_pairs < min_conflict_comparable_pairs:
        conflict_gate_skip_reasons.append("low_comparable_pairs")
    if conflict_pairs < min_conflict_pairs:
        conflict_gate_skip_reasons.append("low_conflict_pairs")
    conflict_gate_skipped = bool(conflict_gate_skip_reasons)

    # Multi-evidence coverage: fraction of validated claims backed by 2+ chunks
    multi_evidence_count = sum(
        1 for c in validated
        if len(c.get("origin_chunk_ids") or []) >= 2
    )
    multi_evidence_coverage_ratio = float(multi_evidence_count) / float(max(1, len(validated)))

    gate_fail_reasons: list[str] = []
    if total <= 0:
        gate_fail_reasons.append("no_claims")
    if supported_ratio < min_supported:
        gate_fail_reasons.append("supported_claim_ratio")
    if (not step_coverage_bypass_excellent) and step_coverage < min_coverage:
        gate_fail_reasons.append("step_coverage_ratio")
    if (not critical_slot_bypass_excellent) and float(completeness.get("critical_slot_coverage") or 0.0) < min_critical:
        gate_fail_reasons.append("critical_slot_coverage")
    if (not conflict_gate_skipped) and float(conflict.get("conflict_rate") or 0.0) > max_conflict:
        gate_fail_reasons.append("conflict_rate")
    if non_method_critical_claims < base_min_non_method_critical_claims:
        gate_fail_reasons.append("non_method_critical_claims")
    if result_like_claims < base_min_result_like_claims:
        gate_fail_reasons.append("result_like_claims")
    if result_like_ratio < base_min_result_like_ratio:
        gate_fail_reasons.append("result_like_ratio")
    # P1 Fix: Hybrid/semantic grounding coverage gate.
    # When min_semantic_coverage > 0.0, gate fails if fewer claims went through semantic judgment
    # than the configured minimum ratio (default: 0.0 = disabled, backwards compatible).
    if min_semantic_coverage > 0.0 and grounding_semantic_coverage_rate < min_semantic_coverage:
        gate_fail_reasons.append("semantic_coverage")
    gate_passed = not gate_fail_reasons
    tier_info = _quality_tier_from_failures(gate_fail_reasons, rules=rules)

    return {
        "total_claims": total,
        "validated_claims": len(validated),
        "supported_claims": supported,
        "weak_claims": weak,
        "unsupported_claims": unsupported,
        "supported_claim_ratio": supported_ratio,
        "step_coverage_ratio": step_coverage,
        "logic_steps_coverage_ratio": logic_steps_coverage,
        "logic_covered_steps_count": len(logic_covered_steps_set),
        "validated_steps_missing_logic": validated_steps_missing_logic,
        "logic_steps_guard_validated_enabled": logic_steps_guard_validated_enabled,
        "logic_steps_guard_validated_ready": logic_steps_guard_validated_ready,
        "grounding_mode_used": grounding_mode_used,
        "grounding_semantic_judged": grounding_semantic_judged,
        "grounding_lexical_judged": grounding_lexical_judged,
        "grounding_semantic_coverage_rate": grounding_semantic_coverage_rate,
        "grounding_fallback_count": grounding_fallback_count,
        "grounding_fallback_warning": grounding_fallback_count > 0,
        "multi_evidence_count": multi_evidence_count,
        "multi_evidence_coverage_ratio": multi_evidence_coverage_ratio,
        "critical_slot_mode": completeness.get("critical_slot_mode"),
        "critical_steps": list(completeness.get("critical_steps") or []),
        "critical_kinds": list(completeness.get("critical_kinds") or []),
        "critical_step_kind_map": dict(completeness.get("critical_step_kind_map") or {}),
        "critical_slots_total": int(completeness.get("critical_slots_total") or 0),
        "critical_slots_covered": int(completeness.get("critical_slots_covered") or 0),
        "critical_slot_coverage": float(completeness.get("critical_slot_coverage") or 0.0),
        "critical_slot_bypass_excellent": critical_slot_bypass_excellent,
        "step_coverage_bypass_excellent": step_coverage_bypass_excellent,
        "critical_steps_with_claims": critical_steps_with_claims,
        "non_method_critical_claims": non_method_critical_claims,
        "result_like_claims": result_like_claims,
        "result_like_ratio": result_like_ratio,
        "missing_critical_slots": list(completeness.get("missing_critical_slots") or []),
        "slot_claim_counts": dict(completeness.get("slot_claim_counts") or {}),
        "step_claim_counts": dict(completeness.get("step_claim_counts") or {}),
        "comparable_pairs": int(conflict.get("comparable_pairs") or 0),
        "conflict_pairs": int(conflict.get("conflict_pairs") or 0),
        "conflict_rate": float(conflict.get("conflict_rate") or 0.0),
        "conflict_samples": list(conflict.get("conflict_samples") or []),
        "conflict_shared_tokens_min": int(conflict.get("shared_tokens_min") or 0),
        "conflict_mode_used": str(conflict.get("conflict_mode_used") or "lexical"),
        "conflict_candidate_pairs": int(conflict.get("conflict_candidate_pairs") or 0),
        "conflict_semantic_judged": int(conflict.get("conflict_semantic_judged") or 0),
        "conflict_semantic_coverage_ratio": float(conflict.get("conflict_semantic_coverage_ratio") or 0.0),
        "conflict_semantic_insufficient_pairs": int(conflict.get("conflict_semantic_insufficient_pairs") or 0),
        "conflict_semantic_insufficient_ratio": float(conflict.get("conflict_semantic_insufficient_ratio") or 0.0),
        "conflict_semantic_missing_pairs": int(conflict.get("conflict_semantic_missing_pairs") or 0),
        "conflict_semantic_unknown_pair_rows": int(conflict.get("conflict_semantic_unknown_pair_rows") or 0),
        "conflict_semantic_threshold": float(conflict.get("conflict_semantic_threshold") or 0.0),
        "conflict_semantic_fallback": bool(conflict.get("conflict_semantic_fallback")),
        "conflict_semantic_fallback_reason": str(conflict.get("conflict_semantic_fallback_reason") or ""),
        "conflict_gate_skipped": conflict_gate_skipped,
        "conflict_gate_skip_reasons": conflict_gate_skip_reasons,
        "conflict_gate_min_comparable_pairs": min_conflict_comparable_pairs,
        "conflict_gate_min_conflict_pairs": min_conflict_pairs,
        "gate_fail_reasons": gate_fail_reasons,
        "gate_passed": gate_passed,
        "quality_tier_strategy": str(tier_info.get("quality_tier_strategy") or "a1_fail_count"),
        "quality_tier": str(tier_info.get("quality_tier") or "red"),
        "quality_tier_fail_count": int(tier_info.get("quality_tier_fail_count") or 0),
        "quality_tier_reasons": list(tier_info.get("quality_tier_reasons") or []),
        "quality_tier_score": float(tier_info.get("quality_tier_score") or 0.0),
        "quality_tier_yellow_max_failures": int(tier_info.get("quality_tier_yellow_max_failures") or 1),
        "quality_tier_red_min_failures": int(tier_info.get("quality_tier_red_min_failures") or 2),
        "thresholds": {
            "gate_profile": gate_profile_name,
            "phase1_gate_supported_ratio_min": min_supported,
            "phase1_gate_step_coverage_min": min_coverage,
            "phase2_gate_critical_slot_coverage_min": min_critical,
            "phase2_gate_critical_slot_bypass_excellent": critical_slot_bypass_enabled,
            "phase2_gate_step_coverage_bypass_excellent": step_coverage_bypass_enabled,
            "phase2_gate_logic_steps_coverage_min": logic_steps_coverage_min,
            "phase2_gate_logic_steps_guard_validated": logic_steps_guard_validated_enabled,
            "phase2_gate_critical_slot_bypass_supported_min": critical_slot_bypass_supported_min,
            "phase2_gate_critical_slot_bypass_min_coverage": critical_slot_bypass_min_coverage,
            "phase2_gate_critical_slot_bypass_min_critical_steps_with_claims": critical_slot_bypass_min_critical_steps_with_claims,
            "phase2_gate_critical_slot_bypass_require_result_or_conclusion": critical_slot_bypass_require_result_or_conclusion,
            "phase2_gate_critical_slot_bypass_min_result_like_claims": critical_slot_bypass_min_result_like_claims,
            "phase2_gate_critical_slot_bypass_min_result_like_ratio": critical_slot_bypass_min_result_like_ratio,
            "phase2_gate_step_bypass_min_critical_steps_with_claims": step_bypass_min_critical_steps_with_claims,
            "phase2_gate_step_bypass_require_non_method_claim": step_bypass_require_non_method_claim,
            "phase2_gate_conflict_rate_max": max_conflict,
            "phase2_gate_base_min_non_method_critical_claims": base_min_non_method_critical_claims,
            "phase2_gate_base_min_result_like_claims": base_min_result_like_claims,
            "phase2_gate_base_min_result_like_ratio": base_min_result_like_ratio,
            "phase1_grounding_mode": grounding_mode_used,
            "phase1_grounding_semantic_supported_min": _rule_float(rules, "phase1_grounding_semantic_supported_min", 0.75),
            "phase1_grounding_semantic_weak_min": _rule_float(rules, "phase1_grounding_semantic_weak_min", 0.55),
            "phase1_gate_semantic_coverage_min": min_semantic_coverage,
            "phase2_conflict_mode": str(conflict.get("conflict_mode_used") or "lexical"),
            "phase2_conflict_semantic_threshold": float(conflict.get("conflict_semantic_threshold") or 0.0),
            "phase2_conflict_gate_min_comparable_pairs": min_conflict_comparable_pairs,
            "phase2_conflict_gate_min_conflict_pairs": min_conflict_pairs,
            "phase2_quality_tier_strategy": str(tier_info.get("quality_tier_strategy") or "a1_fail_count"),
            "phase2_quality_tier_yellow_max_failures": int(tier_info.get("quality_tier_yellow_max_failures") or 1),
            "phase2_quality_tier_red_min_failures": int(tier_info.get("quality_tier_red_min_failures") or 2),
        },
    }


def run_phase1_extraction(
    *,
    doc: DocumentIR,
    paper_id: str,
    cite_rec: dict[str, Any] | None,
    schema: dict[str, Any],
    artifacts_dir: Path | str,
    logic_extractor: LogicExtractorFn | None = None,
    claim_extractor: ClaimExtractorFn | None = None,
    allow_weak: bool = False,
) -> dict[str, Any]:
    artifacts = Path(artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)

    logic_fn = logic_extractor or _default_logic_extractor
    logic_out = logic_fn(doc=doc, paper_id=paper_id, schema=schema)
    logic = dict(logic_out.get("logic") or {})
    step_order = list(logic_out.get("step_order") or _enabled_step_ids(schema))
    _json_dump(artifacts / "logic_steps.json", {"logic": logic, "step_order": step_order})

    chunk_extraction_stats: dict[str, Any] = {}
    if claim_extractor is None:
        extractor_out = _default_claim_extractor(
            doc=doc,
            paper_id=paper_id,
            schema=schema,
            step_order=step_order,
            logic=logic,
        )
        claim_candidates = extractor_out["candidates"]
        chunk_extraction_stats = {
            "chunk_total": extractor_out["chunk_total"],
            "chunk_fail_count": extractor_out["chunk_fail_count"],
            "chunk_fail_rate": (
                extractor_out["chunk_fail_count"] / max(1, extractor_out["chunk_total"])
            ),
        }
    else:
        claim_candidates = claim_extractor(
            doc=doc,
            paper_id=paper_id,
            schema=schema,
            step_order=step_order,
        )
    _json_dump(artifacts / "claim_candidates.json", {"claims": claim_candidates})

    # P0-5: Filter extraction noise
    rules = schema.get("rules") or {}
    noise_filter_stats: dict[str, Any] = {}
    if _rule_bool(rules, "phase1_noise_filter_enabled", False):
        raw_count_before_filter = len(claim_candidates)
        try:
            from app.extraction.noise_filters import filter_claim_candidates

            filtered_claim_candidates, filter_stats = filter_claim_candidates(claim_candidates, rules)
            filter_stats = dict(filter_stats or {})
            noise_filter_stats = {
                "raw_count": _rule_int(filter_stats, "raw_count", raw_count_before_filter),
                "filtered_count": _rule_int(filter_stats, "filtered_count", len(filtered_claim_candidates)),
                "caption_filtered": _rule_int(filter_stats, "caption_filtered", 0),
                "definition_filtered": _rule_int(filter_stats, "definition_filtered", 0),
                "filter_rate": _rule_float(filter_stats, "filter_rate", 0.0),
            }
            logger.info(
                "phase1_noise_filter: "
                "raw=%d "
                "filtered=%d "
                "caption=%d "
                "definition=%d "
                "rate=%.1f%%",
                noise_filter_stats.get("raw_count", 0),
                noise_filter_stats.get("filtered_count", 0),
                noise_filter_stats.get("caption_filtered", 0),
                noise_filter_stats.get("definition_filtered", 0),
                noise_filter_stats.get("filter_rate", 0.0) * 100,
            )

            _json_dump(
                artifacts / "claim_candidates_filtered.json",
                {
                    "claims": filtered_claim_candidates,
                    "noise_filter": noise_filter_stats,
                },
            )
            claim_candidates = filtered_claim_candidates
        except Exception as exc:
            noise_filter_stats = {"error": str(exc)}
            logger.warning(
                "Phase1 noise filter fallback triggered: paper_id=%s raw=%d error=%s",
                paper_id,
                raw_count_before_filter,
                str(exc),
                exc_info=True,
            )

    chunk_by_id = {c.chunk_id: c.text for c in doc.chunks}
    claims_merged = _merge_claim_candidates(
        claims=claim_candidates,
        paper_id=paper_id,
        doi=(doc.paper.doi or ""),
        step_order=step_order,
    )
    _json_dump(artifacts / "claims_merged.json", {"claims": claims_merged})

    # P1-12: Semantic dedup observation (log only, no merging)
    dedup_log: list[dict[str, Any]] = []
    if _rule_bool(rules, "phase1_dedup_observation_enabled", False):
        try:
            dedup_log = _observe_semantic_duplicates(claims_merged, rules=rules)
            if dedup_log:
                _json_dump(artifacts / "dedup_observation.json", {"pairs": dedup_log, "count": len(dedup_log)})
                logger.info("Semantic dedup observation: %d potential duplicate pairs found", len(dedup_log))
        except Exception:
            logger.debug("Semantic dedup observation failed", exc_info=True)

    # Grounding skipped: all claims that passed batch quote verification
    # are directly marked as supported (phase1_grounding_mode=skip).
    judgments = [
        {
            "canonical_claim_id": str(c.get("canonical_claim_id") or c.get("claim_id") or ""),
            "support_label": "supported",
            "judge_score": 1.0,
            "reason": "quote verified at extraction",
            "judge_mode": "skip",
            "judge_fallback": False,
            "judge_fallback_reason": "",
        }
        for c in claims_merged
    ]
    _json_dump(artifacts / "grounding_judgment.json", {"judgments": judgments})
    by_claim_id = {str(j.get("canonical_claim_id") or ""): j for j in judgments}

    validated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for claim in claims_merged:
        cid = str(claim.get("canonical_claim_id") or claim.get("claim_id") or "")
        j = by_claim_id.get(cid) or {}
        out_item = {
            "claim_id": claim["claim_id"],
            "claim_key": claim["claim_key"],
            "text": claim["text"],
            "confidence": float(claim.get("confidence") or 0.5),
            "step_type": claim["step_type"],
            "kinds": list(claim.get("kinds") or []),
            "evidence_chunk_ids": list(
                claim.get("origin_chunk_ids")
                or ([claim["origin_chunk_id"]] if claim.get("origin_chunk_id") else [])
            ),
            "origin_chunk_ids": list(claim.get("origin_chunk_ids") or []),
            "span_start": int(claim["span_start"]) if "span_start" in claim and claim["span_start"] is not None else -1,
            "span_end": int(claim["span_end"]) if "span_end" in claim and claim["span_end"] is not None else -1,
            "match_mode": str(claim.get("match_mode") or "none"),
            "evidence_quote": str(claim.get("evidence_quote") or ""),
            "match_confidence": 1.0,
            "support_label": "supported",
            "judge_score": 1.0,
            "judge_reason": "quote verified at extraction",
            "evidence_weak": False,
            "targets_paper_ids": [],
        }
        validated.append(out_item)

    _attach_targets_from_citations(validated, cite_rec=cite_rec, schema=schema)
    _attach_targets_from_citations(rejected, cite_rec=cite_rec, schema=schema)

    # Compute logic steps coverage ratio: fraction of schema steps that have a
    # non-empty summary or evidence in the logic extraction output.
    # Uses step_order (full schema step list) as the denominator, consistent with
    # step_coverage_ratio. This is used by excellent bypass rules (critical-slot
    # and optional step-coverage bypass) so that papers
    # whose claims concentrate in fewer steps (e.g. software/theory papers) can
    # still pass the gate when their logic structure is fully populated.
    _step_ids_all = [str(s or "").strip() for s in step_order if str(s or "").strip()]
    logic_covered_steps = {
        _sid
        for _sid in _step_ids_all
        if (
            bool((logic.get(_sid) or {}).get("summary_machine", "").strip())
            or bool((logic.get(_sid) or {}).get("summary", "").strip())
            or bool((logic.get(_sid) or {}).get("evidence_chunk_ids"))
        )
    }
    logic_steps_coverage_ratio = float(len(logic_covered_steps)) / float(max(1, len(_step_ids_all)))

    # P0 Fix: Check for empty logic steps
    logic_steps_empty_count = 0
    for step_id, step_data in logic.items():
        summary = step_data.get("summary_machine") or step_data.get("summary") or ""
        evidence = step_data.get("evidence_chunk_ids") or []
        if not summary.strip() and not evidence:
            logic_steps_empty_count += 1

    report = _quality_report(
        claims_merged=claims_merged,
        validated=validated,
        judgments=judgments,
        step_order=step_order,
        logic_steps_coverage_ratio=logic_steps_coverage_ratio,
        logic_covered_steps=logic_covered_steps,
        schema=schema,
        rules=dict(schema.get("rules") or {}),
    )

    # Add noise filter stats to quality report
    if noise_filter_stats:
        report["noise_filter"] = noise_filter_stats

    # P1-12: Add dedup observation stats
    if dedup_log:
        report["dedup_observation"] = {
            "potential_duplicate_pairs": len(dedup_log),
            "threshold": _rule_float(rules, "phase1_dedup_similarity_threshold", 0.92),
        }

    # Add chunk extraction stats (fail rate observability)
    if chunk_extraction_stats:
        report["chunk_extraction"] = chunk_extraction_stats

    # P1-11: chunk_fail_rate gate check
    chunk_fail_rate_max = _rule_float(rules, "phase1_gate_chunk_fail_rate_max", 0.3)
    chunk_fail_rate = float(chunk_extraction_stats.get("chunk_fail_rate") or 0.0) if chunk_extraction_stats else 0.0
    if chunk_fail_rate > chunk_fail_rate_max:
        gate_fail_reasons = list(report.get("gate_fail_reasons") or [])
        gate_fail_reasons.append("chunk_fail_rate")
        report["gate_fail_reasons"] = gate_fail_reasons
        report["gate_passed"] = False
        tier_info = _quality_tier_from_failures(gate_fail_reasons, rules=rules)
        report["quality_tier_strategy"] = str(tier_info.get("quality_tier_strategy") or "a1_fail_count")
        report["quality_tier"] = str(tier_info.get("quality_tier") or "red")
        report["quality_tier_fail_count"] = int(tier_info.get("quality_tier_fail_count") or 0)
        report["quality_tier_reasons"] = list(tier_info.get("quality_tier_reasons") or [])
        report["quality_tier_score"] = float(tier_info.get("quality_tier_score") or 0.0)

    # P0 Fix: Add empty logic steps count to report and update gate
    report["logic_steps_empty_count"] = logic_steps_empty_count
    if logic_steps_empty_count > 0:
        # Add to gate fail reasons if empty steps exist
        gate_fail_reasons = list(report.get("gate_fail_reasons") or [])
        gate_fail_reasons.append("empty_logic_steps")
        report["gate_fail_reasons"] = gate_fail_reasons
        report["gate_passed"] = False
        # P0-3 Fix: Recalculate quality_tier to stay consistent with gate_passed
        tier_info = _quality_tier_from_failures(gate_fail_reasons, rules=rules)
        report["quality_tier_strategy"] = str(tier_info.get("quality_tier_strategy") or "a1_fail_count")
        report["quality_tier"] = str(tier_info.get("quality_tier") or "red")
        report["quality_tier_fail_count"] = int(tier_info.get("quality_tier_fail_count") or 0)
        report["quality_tier_reasons"] = list(tier_info.get("quality_tier_reasons") or [])
        report["quality_tier_score"] = float(tier_info.get("quality_tier_score") or 0.0)

    completeness_judgment = {
        "critical_slot_mode": report.get("critical_slot_mode"),
        "critical_steps": list(report.get("critical_steps") or []),
        "critical_kinds": list(report.get("critical_kinds") or []),
        "critical_step_kind_map": dict(report.get("critical_step_kind_map") or {}),
        "critical_slots_total": int(report.get("critical_slots_total") or 0),
        "critical_slots_covered": int(report.get("critical_slots_covered") or 0),
        "critical_slot_coverage": float(report.get("critical_slot_coverage") or 0.0),
        "missing_critical_slots": list(report.get("missing_critical_slots") or []),
    }
    _json_dump(artifacts / "completeness_judgment.json", completeness_judgment)
    _json_dump(
        artifacts / "quality_report.json",
        {
            "quality_report": report,
            "validated_claims": len(validated),
            "rejected_claims": len(rejected),
        },
    )

    return {
        "logic": logic,
        "step_order": step_order,
        "claim_candidates": claim_candidates,
        "claims_merged": claims_merged,
        "grounding_judgment": judgments,
        "completeness_judgment": completeness_judgment,
        "validated_claims": validated,
        "rejected_claims": rejected,
        "quality_report": report,
    }
