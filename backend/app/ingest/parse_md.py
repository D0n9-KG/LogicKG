from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

from app.ingest.models import (
    Chunk,
    CitationEvent,
    DocumentIR,
    MdSpan,
    PaperDraft,
    ReferenceEntry,
)
from app.text_normalization import normalize_ingested_markdown


_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")
_DOI_RE = re.compile(r"\bDOI:\s*(?P<doi>10\.\d{4,9}/[^\s]+)", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# matches [1], [2,3], [13-15], [13–15]
_IN_TEXT_CITATION_RE = re.compile(
    r"\[(?P<body>\d{1,3}(?:\s*[,\u2013\-–]\s*\d{1,3})*)\]"
)
_REF_ENTRY_RE = re.compile(r"^\[(?P<num>\d{1,3})\]\s+(?P<rest>.+?)\s*$")

# For detecting unnumbered references (MLA/APA style)
_REF_HEADING_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*)?(references|bibliography|reference list|works cited|参考文献)\s*$",
    re.IGNORECASE,
)
_SECTION_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")


def _looks_like_reference(line: str) -> bool:
    """Heuristic to detect if a line looks like a reference entry."""
    if len(line) < 12:
        return False
    lower = line.lower()
    norm = line.strip()

    # Has year pattern
    has_year = bool(_YEAR_RE.search(norm))
    # Has doi or common reference markers
    has_markers = ("doi" in lower) or ("," in norm and "." in norm)
    # Has publication-like punctuation
    has_pub_pattern = norm.count(",") >= 2 or (norm.count(".") >= 2 and "." not in norm[-3:])

    return has_year and (has_markers or has_pub_pattern)


def _stable_chunk_id(paper_source: str, md_path: str, start_line: int, end_line: int, text: str) -> str:
    h = hashlib.sha256()
    h.update(paper_source.encode("utf-8", errors="ignore"))
    h.update(b"\0")
    h.update(str(start_line).encode())
    h.update(b":")
    h.update(str(end_line).encode())
    h.update(b"\0")
    h.update(text.strip().encode("utf-8", errors="ignore"))
    digest = h.hexdigest()[:16]
    base = f"{paper_source}:{start_line}-{end_line}:{digest}"
    return base


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _expand_citation_body(body: str) -> list[int]:
    # body examples: "1", "2,3", "13-15", "13–15", "13-15, 19"
    parts = re.split(r"\s*,\s*", body)
    nums: list[int] = []
    for part in parts:
        if not part:
            continue
        if re.search(r"[\u2013\-–]", part):
            a, b = re.split(r"\s*[\u2013\-–]\s*", part, maxsplit=1)
            try:
                start = int(a)
                end = int(b)
            except ValueError:
                continue
            if 0 < start <= 999 and 0 < end <= 999 and start <= end:
                nums.extend(list(range(start, end + 1)))
        else:
            try:
                n = int(part)
            except ValueError:
                continue
            if 0 < n <= 999:
                nums.append(n)
    # preserve order but remove duplicates
    seen: set[int] = set()
    out: list[int] = []
    for n in nums:
        if n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def parse_mineru_markdown(md_path: str) -> DocumentIR:
    p = Path(md_path)
    if not p.exists():
        raise FileNotFoundError(f"Markdown not found: {md_path}")

    # MinerU output is sometimes not strictly UTF-8; ignore errors to keep pipeline robust.
    raw = normalize_ingested_markdown(
        p.read_text(encoding="utf-8", errors="ignore")
    )
    lines = raw.splitlines()

    paper_source = p.parent.name or p.stem

    section_cursor: str | None = None
    heading_titles: list[str] = []
    authors: list[str] = []
    doi: str | None = None
    year: int | None = None

    # Heuristics: top headings for titles, early non-empty line for authors, DOI line anywhere.
    for i, line in enumerate(lines[:80], start=1):
        m = _HEADING_RE.match(line)
        if m:
            t = _normalize_space(m.group("title"))
            if t:
                heading_titles.append(t)
            continue
        if not authors and i > 1 and line.strip() and not line.startswith("![](") and "School of" not in line:
            # a crude "authors line": contains commas or "and"
            if "," in line or " and " in line:
                candidates = re.split(r"\s+and\s+|,\s*", line.strip())
                authors = [c.strip() for c in candidates if c.strip()]

    m = _DOI_RE.search(raw)
    if m:
        doi = m.group("doi").rstrip(").,;")

    # Prefer the latest year (often the publication year).
    years: list[int] = []
    for ym in _YEAR_RE.finditer(raw):
        try:
            y = int(ym.group(0))
        except ValueError:
            continue
        if 1900 <= y <= datetime.now().year + 1:
            years.append(y)
    if years:
        # Prefer the latest year (often the publication year)
        year = max(years)

    def title_score(t: str) -> int:
        # Prefer clean English titles when MinerU produces garbled non-UTF8 headings.
        ascii_alnum = sum(1 for ch in t if ord(ch) < 128 and ch.isalnum())
        penalty = 20 * t.count("\ufffd") + 10 * t.count("?")
        return ascii_alnum - penalty + len(t)

    title = None
    title_alt = None
    if heading_titles:
        ranked = sorted({t for t in heading_titles if t}, key=title_score, reverse=True)
        title = ranked[0] if ranked else None
        title_alt = ranked[1] if len(ranked) > 1 else None

    chunks: list[Chunk] = []
    references: list[ReferenceEntry] = []
    citations: list[CitationEvent] = []

    # Identify reference entries near the end: collect all lines that look like "[n] ..."
    ref_line_idxs: list[int] = []
    ref_heading_idx: int | None = None
    for idx, line in enumerate(lines, start=1):
        if _REF_ENTRY_RE.match(line.strip()):
            ref_line_idxs.append(idx)
        # Also detect reference section headings (take last match to avoid early TOC/mentions)
        if _REF_HEADING_RE.match(line.strip()):
            ref_heading_idx = idx

    ref_start = None
    if ref_line_idxs:
        # assume references start at the first ref line after the last non-ref block near the end
        ref_start = ref_line_idxs[0]
        # a better heuristic: if ref lines are concentrated near end, choose first within last 30% of file
        cutoff = int(len(lines) * 0.7)
        tail_refs = [i for i in ref_line_idxs if i >= cutoff]
        if tail_refs:
            ref_start = min(tail_refs)
    elif ref_heading_idx:
        # No numbered refs found, but we have a reference heading - use it
        ref_start = ref_heading_idx

    # Build paragraph-like chunks by blank-line separation, but stop parsing at reference section for "content chunks".
    blocks: list[tuple[int, int, str, str | None]] = []
    current: list[str] = []
    block_start = 1
    max_line = len(lines)

    def flush_block(end_line: int):
        nonlocal current, block_start
        if not current:
            block_start = end_line + 1
            return
        text = "\n".join(current).strip()
        if text:
            blocks.append((block_start, end_line, text, section_cursor))
        current = []
        block_start = end_line + 1

    for idx, line in enumerate(lines, start=1):
        if ref_start and idx >= ref_start:
            # do not include references in content chunks; we'll parse references separately
            break
        if _HEADING_RE.match(line):
            flush_block(idx - 1)
            section_cursor = _normalize_space(_HEADING_RE.match(line).group("title"))  # type: ignore[union-attr]
            # headings themselves become tiny chunks so we can point spans at them if needed
            blocks.append((idx, idx, line.strip(), section_cursor))
            continue
        if line.strip() == "":
            flush_block(idx - 1)
            continue
        current.append(line)
    flush_block((ref_start - 1) if ref_start else max_line)

    paper_draft = PaperDraft(
        paper_source=paper_source,
        md_path=str(p),
        title=title,
        title_alt=title_alt,
        authors=authors,
        doi=doi,
        year=year,
    )

    for start, end, text, block_section in blocks:
        kind = "heading" if _HEADING_RE.match(text.strip()) else "block"
        chunk_id = _stable_chunk_id(paper_source, str(p), start, end, text)
        span = MdSpan(start_line=start, end_line=end)
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                paper_source=paper_source,
                md_path=str(p),
                span=span,
                section=block_section,
                kind=kind,
                text=text,
            )
        )

        # in-text citation events within this chunk
        for cm in _IN_TEXT_CITATION_RE.finditer(text):
            body = cm.group("body")
            for n in _expand_citation_body(body):
                citations.append(
                    CitationEvent(
                        paper_source=paper_source,
                        md_path=str(p),
                        cited_ref_num=n,
                        chunk_id=chunk_id,
                        span=span,
                        context=_normalize_space(text)[:800],
                    )
                )

    # Parse references (only if detected)
    if ref_start:
        # Strategy: try numbered first, fallback to unnumbered with multi-line merging
        numbered_refs: dict[int, str] = {}
        unnumbered_refs: list[str] = []
        current_ref = ""
        current_num: int | None = None
        in_references = True  # We're already starting from ref_start, so we're in references

        for idx in range(ref_start, len(lines) + 1):
            line = lines[idx - 1].strip()

            # Skip reference section heading itself
            if _REF_HEADING_RE.match(line):
                in_references = True
                continue

            # Stop at next major section heading
            if in_references and _SECTION_HEADING_RE.match(line) and not _REF_HEADING_RE.match(line):
                break

            if not line:
                # Empty line: save current ref
                if current_num is not None and current_ref:
                    numbered_refs[current_num] = current_ref.strip()
                    current_ref = ""
                    current_num = None
                elif current_ref and _looks_like_reference(current_ref):
                    unnumbered_refs.append(current_ref.strip())
                    current_ref = ""
                continue

            # Check for numbered reference
            m = _REF_ENTRY_RE.match(line)
            if m:
                # Save previous reference
                if current_num is not None and current_ref:
                    numbered_refs[current_num] = current_ref.strip()
                elif current_ref and _looks_like_reference(current_ref):
                    unnumbered_refs.append(current_ref.strip())

                # Start new numbered reference
                current_num = int(m.group("num"))
                current_ref = m.group("rest").strip()
            elif current_num is not None:
                # Continuation of numbered reference
                current_ref += " " + line
            elif _looks_like_reference(line):
                # Unnumbered refs: if we already hold a full ref-like line, start a new ref.
                if current_ref and current_num is None and _looks_like_reference(current_ref):
                    unnumbered_refs.append(current_ref.strip())
                    current_ref = line
                elif current_ref:
                    current_ref += " " + line
                else:
                    current_ref = line
            elif current_ref:
                # Might be continuation line
                current_ref += " " + line

        # Save last reference
        if current_num is not None and current_ref:
            numbered_refs[current_num] = current_ref.strip()
        elif current_ref and _looks_like_reference(current_ref):
            unnumbered_refs.append(current_ref.strip())

        # Build references list
        if numbered_refs:
            # Numbered references found - use them
            for num in sorted(numbered_refs.keys()):
                references.append(
                    ReferenceEntry(
                        paper_source=paper_source,
                        md_path=str(p),
                        ref_num=num,
                        raw=numbered_refs[num],
                    )
                )
        elif unnumbered_refs:
            # No numbered refs, use unnumbered with sequential numbering
            for i, raw in enumerate(unnumbered_refs, start=1):
                references.append(
                    ReferenceEntry(
                        paper_source=paper_source,
                        md_path=str(p),
                        ref_num=i,
                        raw=raw,
                    )
                )

    return DocumentIR(paper=paper_draft, chunks=chunks, references=references, citations=citations)


def find_mineru_markdowns(root_path: str) -> list[str]:
    root = Path(root_path)
    if not root.exists():
        raise FileNotFoundError(f"Path not found: {root_path}")

    def is_project_root_dir(p: Path) -> bool:
        # Heuristic: if this looks like the repo root, don't treat root-level *.md as MinerU paper md.
        return any((p / d).exists() for d in ("backend", "frontend", "docs", ".git"))

    excluded_dirnames = {
        ".git",
        ".venv",
        "__pycache__",
        "backend",
        "docs",
        "frontend",
        "node_modules",
        "dist",
        "runs",
    }

    mds: list[str] = []

    def add_md_in_dir(dir_path: Path, filenames: list[str], require_images: bool) -> None:
        if require_images and not (dir_path / "images").is_dir():
            return
        for fn in filenames:
            if not fn.lower().endswith(".md"):
                continue
            if fn.lower() == "readme.md":
                continue
            mds.append(str(dir_path / fn))

    # Preferred: MinerU paper folder layout usually contains "images/" next to the markdown.
    # If the user points directly at a paper folder, accept root-level *.md when images/ exists.
    if not is_project_root_dir(root):
        add_md_in_dir(root, [p.name for p in root.glob("*.md")], require_images=True)

    # Walk recursively while pruning huge/unrelated dirs (important on Windows where node_modules/.venv are large).
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in excluded_dirnames]
        dp = Path(dirpath)
        # If root is project root, skip root-level markdowns (README, notes, etc.).
        if is_project_root_dir(root) and dp == root:
            continue
        add_md_in_dir(dp, filenames, require_images=True)

    # Fallback: if nothing matched the MinerU images/ heuristic, fall back to any *.md found
    # (still respects directory pruning), so the pipeline can be used on text-only corpora.
    if not mds:
        if not is_project_root_dir(root):
            add_md_in_dir(root, [p.name for p in root.glob("*.md")], require_images=False)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in excluded_dirnames]
            dp = Path(dirpath)
            if is_project_root_dir(root) and dp == root:
                continue
            add_md_in_dir(dp, filenames, require_images=False)

    return sorted({m for m in mds})
