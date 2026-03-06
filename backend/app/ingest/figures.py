from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


_IMG_RE = re.compile(r"!\[[^\]]*\]\((?P<path>[^)]+)\)")
_CAPTION_RE = re.compile(r"^(fig\.?|figure|图)\s*\d+", re.IGNORECASE)


@dataclass(frozen=True)
class FigureRecord:
    figure_id: str
    paper_id: str
    md_path: str
    rel_path: str
    filename: str
    img_line: int
    caption_text: str | None
    caption_start_line: int | None
    caption_end_line: int | None


def _safe_rel(p: str) -> str | None:
    s = (p or "").strip().strip("\"'").replace("\\", "/")
    if not s:
        return None
    if s.startswith("http://") or s.startswith("https://"):
        return None
    if " " in s:
        s = s.split(" ", 1)[0].strip()
    parts = [x for x in s.split("/") if x not in {"", "."}]
    if any(x == ".." for x in parts):
        return None
    return "/".join(parts)


def extract_figures_from_markdown(paper_id: str, md_path: str) -> list[FigureRecord]:
    p = Path(md_path)
    raw = p.read_text(encoding="utf-8", errors="ignore")
    lines = raw.splitlines()
    out: list[FigureRecord] = []

    for i, line in enumerate(lines, start=1):
        m = _IMG_RE.search(line)
        if not m:
            continue
        rel = _safe_rel(m.group("path") or "")
        if not rel:
            continue
        # Only treat MinerU images folder as figures for now.
        if not rel.startswith("images/"):
            continue
        rel_img = rel[len("images/") :]
        filename = Path(rel_img).name

        caption_text = None
        cap_start = None
        cap_end = None

        # Prefer previous line if it looks like a caption header.
        if i > 1 and lines[i - 2].strip() and _CAPTION_RE.match(lines[i - 2].strip()):
            caption_text = lines[i - 2].strip()
            cap_start = i - 1
            cap_end = i - 1
        else:
            # Otherwise take the next non-empty line block (up to 3 lines) within a small window.
            buf: list[str] = []
            start = None
            for j in range(i + 1, min(len(lines) + 1, i + 8)):
                t = lines[j - 1].strip()
                if not t:
                    if buf:
                        break
                    continue
                if _IMG_RE.search(t):
                    break
                if start is None:
                    start = j
                buf.append(t)
                if len(buf) >= 3:
                    break
            if buf and start is not None:
                caption_text = " ".join(buf).strip()
                cap_start = start
                cap_end = start + len(buf) - 1

        h = hashlib.sha256()
        h.update(paper_id.encode("utf-8", errors="ignore"))
        h.update(b"\0")
        h.update(rel_img.encode("utf-8", errors="ignore"))
        h.update(b"\0")
        h.update(str(i).encode())
        figure_id = f"{paper_id}:fig:{h.hexdigest()[:16]}"

        out.append(
            FigureRecord(
                figure_id=figure_id,
                paper_id=paper_id,
                md_path=str(p),
                rel_path=rel_img,
                filename=filename,
                img_line=i,
                caption_text=caption_text,
                caption_start_line=cap_start,
                caption_end_line=cap_end,
            )
        )

    return out
