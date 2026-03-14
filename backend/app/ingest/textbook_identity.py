from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from app.text_normalization import normalize_ingested_markdown


_H1_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_H2_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class TextbookIdentity:
    inferred_title: str
    normalized_title: str
    content_fingerprint: str
    textbook_id: str


def normalize_textbook_title(title: str | None) -> str:
    value = re.sub(r"\s+", " ", str(title or "").strip()).lower()
    return value or "untitled"


def fingerprint_textbook_content(text: str | None) -> str:
    normalized = normalize_ingested_markdown(str(text or "")).replace("\r\n", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()[:24]


def build_textbook_id(title: str | None, content_fingerprint: str | None) -> str:
    normalized_title = normalize_textbook_title(title)
    normalized_fingerprint = str(content_fingerprint or "").strip().lower() or "no-fingerprint"
    seed = f"tb:v2\0{normalized_title}\0{normalized_fingerprint}"
    return "tb:" + hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:24]


def infer_textbook_title(md_path: str | Path) -> str:
    path = Path(md_path)
    text = normalize_ingested_markdown(path.read_text(encoding="utf-8", errors="replace"))
    match = _H1_RE.search(text) or _H2_RE.search(text)
    if match:
        title = re.sub(r"\s+", " ", str(match.group(1) or "").strip())
        if title:
            return title
    return path.stem


def infer_textbook_identity(md_path: str | Path) -> TextbookIdentity:
    path = Path(md_path)
    text = path.read_text(encoding="utf-8", errors="replace")
    inferred_title = infer_textbook_title(path)
    normalized_title = normalize_textbook_title(inferred_title)
    content_fingerprint = fingerprint_textbook_content(text)
    textbook_id = build_textbook_id(inferred_title, content_fingerprint)
    return TextbookIdentity(
        inferred_title=inferred_title,
        normalized_title=normalized_title,
        content_fingerprint=content_fingerprint,
        textbook_id=textbook_id,
    )
