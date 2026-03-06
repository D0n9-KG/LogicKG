"""Textbook markdown splitter.

Splits a textbook .md file into chapters by heading level.
Primary split: ``# `` (H1). Fallback: ``## `` (H2) when no H1 headings exist.
Content before the first heading is collected as chapter 0 (preface).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ChapterUnit:
    chapter_num: int
    title: str
    body: str
    start_line: int
    end_line: int


_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def split_textbook_md(md_path: str) -> list[ChapterUnit]:
    """Split a textbook markdown file into chapters.

    Strategy:
    1. Try splitting on ``# `` (H1) headings.
    2. If no H1 headings found, fall back to ``## `` (H2).
    3. Any content before the first heading becomes chapter 0 (preface).

    Returns a list of :class:`ChapterUnit` sorted by ``chapter_num``.
    """
    text = Path(md_path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)

    # Detect heading level to split on
    heading_re = _H1_RE
    if not _H1_RE.search(text):
        heading_re = _H2_RE

    # Find all heading positions, skipping fenced code blocks
    headings: list[tuple[int, str]] = []  # (line_index, title)
    prefix = "#" if heading_re is _H1_RE else "##"
    in_code_block = False
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if stripped.startswith(prefix + " ") and not stripped.startswith(prefix + "# "):
            title = stripped[len(prefix) :].strip()
            if title:
                headings.append((idx, title))

    if not headings:
        # No headings at all — treat entire file as one chapter
        return [ChapterUnit(chapter_num=1, title="Full Document", body=text, start_line=1, end_line=len(lines))]

    chapters: list[ChapterUnit] = []

    # Preface: content before first heading
    first_heading_line = headings[0][0]
    if first_heading_line > 0:
        preface_body = "".join(lines[:first_heading_line]).strip()
        if preface_body:
            chapters.append(ChapterUnit(
                chapter_num=0,
                title="Preface",
                body=preface_body,
                start_line=1,
                end_line=first_heading_line,
            ))

    # Split by headings
    for i, (line_idx, title) in enumerate(headings):
        start = line_idx
        end = headings[i + 1][0] if i + 1 < len(headings) else len(lines)
        body = "".join(lines[start:end]).strip()
        chapters.append(ChapterUnit(
            chapter_num=i + 1,
            title=title,
            body=body,
            start_line=start + 1,  # 1-based
            end_line=end,
        ))

    return chapters
