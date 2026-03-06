from __future__ import annotations

import re
from typing import Any

from app.ingest.models import CitationEvent, DocumentIR


_WS_RE = re.compile(r"\s+")
_YEAR_RE = re.compile(r"(?P<year>(?:19|20)\d{2})(?:[a-z])?", re.IGNORECASE)
_REF_PREFIX_RE = re.compile(r"^\s*(?:\[\d{1,4}\]|\(\d{1,4}\)|\d{1,4}[.)])\s*")
_BRACKET_NUM_RE = re.compile(r"\[(?P<body>\d{1,3}(?:\s*[,，\u2013\u2014\-]\s*\d{1,3})*)\]")
_PAREN_NUM_RE = re.compile(r"[（(](?P<body>\d{1,3}(?:\s*[,，]\s*\d{1,3})*)[)）]")
_PAREN_BODY_RE = re.compile(r"[（(](?P<body>[^()（）]{3,220})[)）]")
_NAME_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'`-]{1,}")
_DIGIT_TOKEN_RE = re.compile(r"^\d+$")
_SEPARATOR_RE = re.compile(r"[;；]")

_NAME_STOP_TOKENS = {
    "and",
    "et",
    "al",
    "al.",
    "the",
    "in",
    "on",
    "for",
    "of",
    "to",
    "with",
    "by",
    "from",
    "via",
    "using",
    "use",
    "based",
    "this",
    "that",
    "these",
    "those",
    "figure",
    "eq",
    "equation",
}


def _rule_bool(rules: dict[str, Any], key: str, default: bool) -> bool:
    raw = rules.get(key, default)
    if isinstance(raw, bool):
        return raw
    s = str(raw or "").strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _rule_int(rules: dict[str, Any], key: str, default: int, *, lo: int, hi: int) -> int:
    try:
        raw = rules.get(key, default)
        v = int(raw)
    except Exception:
        v = int(default)
    return max(lo, min(hi, v))


def _normalize_space(text: str) -> str:
    return _WS_RE.sub(" ", str(text or "")).strip()


def _expand_num_body(body: str) -> list[int]:
    parts = re.split(r"\s*[,，]\s*", str(body or "").strip())
    out: list[int] = []
    for part in parts:
        if not part:
            continue
        if re.search(r"[\u2013\u2014\-]", part):
            try:
                left, right = re.split(r"\s*[\u2013\u2014\-]\s*", part, maxsplit=1)
                start = int(left)
                end = int(right)
            except Exception:
                continue
            if start <= 0 or end <= 0 or start > end or end > 999:
                continue
            out.extend(list(range(start, end + 1)))
            continue
        try:
            n = int(part)
        except Exception:
            continue
        if 0 < n <= 999:
            out.append(n)
    dedup: list[int] = []
    seen: set[int] = set()
    for x in out:
        if x in seen:
            continue
        seen.add(x)
        dedup.append(x)
    return dedup


def _year_key(text: str) -> str:
    m = _YEAR_RE.search(str(text or ""))
    if not m:
        return ""
    return str(m.group("year") or "")


def _ref_author_year_index(doc: DocumentIR) -> dict[tuple[str, str], set[int]]:
    idx: dict[tuple[str, str], set[int]] = {}
    for ref in doc.references or []:
        year = _year_key(ref.raw)
        if not year:
            continue
        raw = _REF_PREFIX_RE.sub("", str(ref.raw or "")).strip()
        ym = _YEAR_RE.search(raw)
        prefix = raw[: ym.start()] if ym else raw
        tokens = [t.strip(" .,;:()[]{}").lower() for t in _NAME_TOKEN_RE.findall(prefix)]
        tokens = [t for t in tokens if t and len(t) >= 3 and t not in _NAME_STOP_TOKENS and not _DIGIT_TOKEN_RE.match(t)]
        if not tokens:
            continue
        for surname in dict.fromkeys(tokens[:12]).keys():
            key = (year, surname)
            idx.setdefault(key, set()).add(int(ref.ref_num))
    return idx


def _extract_author_year_refnums(
    text: str,
    *,
    ref_idx: dict[tuple[str, str], set[int]],
    ref_nums: set[int],
) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for m in _PAREN_BODY_RE.finditer(str(text or "")):
        body = str(m.group("body") or "").strip()
        if not body:
            continue
        if not _YEAR_RE.search(body):
            continue
        if not re.search(r"[A-Za-z]", body):
            continue
        for seg in _SEPARATOR_RE.split(body):
            seg = seg.strip()
            if not seg:
                continue
            for ym in _YEAR_RE.finditer(seg):
                year = str(ym.group("year") or "")
                if not year:
                    continue
                left = seg[max(0, ym.start() - 80) : ym.start()]
                tokens = [t.strip(" .,;:()[]{}").lower() for t in _NAME_TOKEN_RE.findall(left)]
                tokens = [t for t in tokens if t and len(t) >= 3 and t not in _NAME_STOP_TOKENS and not _DIGIT_TOKEN_RE.match(t)]
                if not tokens:
                    continue
                candidates: set[int] = set()
                # Prefer tokens nearest to year first (reverse order).
                for token in reversed(tokens):
                    candidates.update(ref_idx.get((year, token), set()))
                    if len(candidates) > 1:
                        break
                if len(candidates) == 1:
                    ref_num = next(iter(candidates))
                    if ref_num in ref_nums and ref_num not in seen:
                        seen.add(ref_num)
                        out.append(ref_num)
    return out


def recover_citation_events_from_references(
    doc: DocumentIR,
    *,
    rules: dict[str, Any] | None = None,
) -> tuple[DocumentIR, dict[str, Any]]:
    rules = dict(rules or {})
    before_events = len(doc.citations or [])
    refs = doc.references or []
    ref_nums = {int(r.ref_num) for r in refs if int(r.ref_num) > 0}
    trigger_max_existing_events = _rule_int(rules, "citation_event_recovery_trigger_max_existing_events", 6, lo=0, hi=50)
    enabled = _rule_bool(rules, "citation_event_recovery_enabled", True)
    numeric_bracket_enabled = _rule_bool(rules, "citation_event_recovery_numeric_bracket_enabled", True)
    paren_numeric_enabled = _rule_bool(rules, "citation_event_recovery_paren_numeric_enabled", False)
    author_year_enabled = _rule_bool(rules, "citation_event_recovery_author_year_enabled", True)
    max_events_per_chunk = _rule_int(rules, "citation_event_recovery_max_events_per_chunk", 6, lo=1, hi=40)
    context_chars = _rule_int(rules, "citation_event_recovery_context_chars", 800, lo=120, hi=4000)

    # Calculate dynamic threshold: papers with more references should allow more existing events before skipping
    # Formula: min(trigger_max + refs*0.15, trigger_max*3)
    # E.g., paper with 20 refs: min(6 + 3, 18) = 9; paper with 40 refs: min(6 + 6, 18) = 12
    ref_count = len(refs)
    dynamic_threshold = max(
        trigger_max_existing_events,
        min(
            trigger_max_existing_events + int(ref_count * 0.15),
            trigger_max_existing_events * 3,
        ),
    )

    report: dict[str, Any] = {
        "enabled": enabled,
        "before_events": before_events,
        "after_events": before_events,
        "before_refs": len(refs),
        "trigger_max_existing_events": trigger_max_existing_events,
        "dynamic_threshold": dynamic_threshold,
        "numeric_bracket_enabled": numeric_bracket_enabled,
        "paren_numeric_enabled": paren_numeric_enabled,
        "author_year_enabled": author_year_enabled,
        "recovered_events": 0,
        "recovered_numeric_events": 0,
        "recovered_author_year_events": 0,
        "status": "pending",
    }

    if not enabled:
        report["status"] = "disabled"
        return doc, report
    if not refs or not ref_nums:
        report["status"] = "no_references"
        return doc, report
    if before_events > dynamic_threshold:
        report["status"] = "skipped_existing_events_above_dynamic_threshold"
        return doc, report

    existing_keys = {(str(c.chunk_id), int(c.cited_ref_num)) for c in (doc.citations or [])}
    recovered: list[CitationEvent] = []
    ref_idx = _ref_author_year_index(doc) if author_year_enabled else {}

    for chunk in doc.chunks or []:
        if str(chunk.kind or "") == "heading":
            continue
        text = str(chunk.text or "")
        if not text.strip():
            continue

        chunk_ref_nums: list[int] = []
        author_year_nums: list[int] = []
        if numeric_bracket_enabled:
            for m in _BRACKET_NUM_RE.finditer(text):
                chunk_ref_nums.extend(_expand_num_body(str(m.group("body") or "")))
        if paren_numeric_enabled:
            for m in _PAREN_NUM_RE.finditer(text):
                chunk_ref_nums.extend(_expand_num_body(str(m.group("body") or "")))
        if author_year_enabled:
            author_year_nums = _extract_author_year_refnums(
                text,
                ref_idx=ref_idx,
                ref_nums=ref_nums,
            )
            chunk_ref_nums.extend(author_year_nums)

        dedup_ref_nums: list[int] = []
        dedup_seen: set[int] = set()
        for num in chunk_ref_nums:
            if num not in ref_nums:
                continue
            if num in dedup_seen:
                continue
            dedup_seen.add(num)
            dedup_ref_nums.append(num)
            if len(dedup_ref_nums) >= max_events_per_chunk:
                break

        if not dedup_ref_nums:
            continue

        context = _normalize_space(text)[:context_chars]
        if not context:
            context = text[:context_chars]
        author_year_set = set(author_year_nums)
        for ref_num in dedup_ref_nums:
            key = (str(chunk.chunk_id), int(ref_num))
            if key in existing_keys:
                continue
            existing_keys.add(key)
            recovered.append(
                CitationEvent(
                    paper_source=doc.paper.paper_source,
                    md_path=doc.paper.md_path,
                    cited_ref_num=int(ref_num),
                    chunk_id=chunk.chunk_id,
                    span=chunk.span,
                    context=context,
                )
            )
            if ref_num in author_year_set:
                report["recovered_author_year_events"] = int(report["recovered_author_year_events"] or 0) + 1
            else:
                report["recovered_numeric_events"] = int(report["recovered_numeric_events"] or 0) + 1

    if not recovered:
        report["status"] = "empty_result"
        return doc, report

    merged = list(doc.citations or []) + recovered
    report["recovered_events"] = len(recovered)
    report["after_events"] = len(merged)
    report["status"] = "recovered"
    return (
        DocumentIR(
            paper=doc.paper,
            chunks=doc.chunks,
            references=doc.references,
            citations=merged,
        ),
        report,
    )
