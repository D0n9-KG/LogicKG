"""Textbook markdown splitter.

Splits a textbook `.md` file into chapter-sized units.

Priority order:
1. Prefer real chapter headings such as `# 第1章 ...` / `# Chapter 1 ...`
2. Fall back to generic `# ` headings
3. Fall back again to `## ` headings when no H1 headings exist

Content before the first detected chapter heading is collected as chapter 0
(`Preface`). Repeated watermark lines are stripped from chapter bodies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.text_normalization import normalize_ingested_markdown


@dataclass
class ChapterUnit:
    chapter_num: int
    title: str
    body: str
    start_line: int
    end_line: int


_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_CHAPTER_H1_RE = re.compile(
    r"^#\s*(?:第\s*(?:\$?\s*\d+\s*\$?|[一二三四五六七八九十百零〇]+)\s*章|chapter\s+\d+)",
    re.IGNORECASE,
)
_WATERMARK_LINE_RE = re.compile(r"^#\s*仅供个人科研教学使用[！! ]*$")
_CHAPTER_NUM_RE = re.compile(
    r"^第\s*(?P<num>\$?\s*\d+\s*\$?|[一二三四五六七八九十百零〇]+)\s*章",
    re.IGNORECASE,
)


_CN_NUM_MAP = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "百": 100,
}


def _clean_body(text: str) -> str:
    cleaned_lines: list[str] = []
    previous_blank = False
    for line in (text or "").splitlines():
        if _WATERMARK_LINE_RE.match(line.strip()):
            continue
        blank = not line.strip()
        if blank and previous_blank:
            continue
        cleaned_lines.append(line.rstrip())
        previous_blank = blank
    return "\n".join(cleaned_lines).strip()


def _collect_headings(lines: list[str], prefix: str) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
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
    return headings


def _prefer_chapter_headings(h1_headings: list[tuple[int, str]]) -> list[tuple[int, str]]:
    chapter_headings = [(idx, title) for idx, title in h1_headings if _CHAPTER_H1_RE.match(f"# {title}")]
    if not chapter_headings:
        return h1_headings
    chapter_numbers = [_extract_chapter_number(title) for _, title in chapter_headings]
    restart_candidates = [idx for idx, num in enumerate(chapter_numbers) if num == 1]
    if restart_candidates:
        return chapter_headings[restart_candidates[-1] :]
    return chapter_headings


def _extract_chapter_number(title: str) -> int | None:
    stripped = (title or "").strip()
    if stripped.lower().startswith("chapter "):
        digits = re.findall(r"\d+", stripped)
        return int(digits[0]) if digits else None
    match = _CHAPTER_NUM_RE.match(stripped)
    if not match:
        return None
    raw = match.group("num").replace("$", "").replace(" ", "")
    if raw.isdigit():
        return int(raw)
    total = 0
    current = 0
    for ch in raw:
        value = _CN_NUM_MAP.get(ch)
        if value is None:
            return None
        if value >= 10:
            current = max(current, 1) * value
            total += current
            current = 0
        else:
            current += value
    return total + current or None


def split_textbook_md(md_path: str) -> list[ChapterUnit]:
    """Split a textbook markdown file into chapters."""
    text = normalize_ingested_markdown(Path(md_path).read_text(encoding="utf-8", errors="replace"))
    lines = text.splitlines(keepends=True)

    heading_re = _H1_RE
    if not _H1_RE.search(text):
        heading_re = _H2_RE

    prefix = "#" if heading_re is _H1_RE else "##"
    headings = _collect_headings(lines, prefix)
    if heading_re is _H1_RE:
        headings = _prefer_chapter_headings(headings)

    if not headings:
        return [ChapterUnit(chapter_num=1, title="Full Document", body=_clean_body(text), start_line=1, end_line=len(lines))]

    chapters: list[ChapterUnit] = []

    first_heading_line = headings[0][0]
    if first_heading_line > 0:
        preface_body = _clean_body("".join(lines[:first_heading_line]))
        if preface_body:
            chapters.append(
                ChapterUnit(
                    chapter_num=0,
                    title="Preface",
                    body=preface_body,
                    start_line=1,
                    end_line=first_heading_line,
                )
            )

    for i, (line_idx, title) in enumerate(headings):
        start = line_idx
        end = headings[i + 1][0] if i + 1 < len(headings) else len(lines)
        body = _clean_body("".join(lines[start:end]))
        chapters.append(
            ChapterUnit(
                chapter_num=i + 1,
                title=title,
                body=body,
                start_line=start + 1,
                end_line=end,
            )
        )

    return chapters
