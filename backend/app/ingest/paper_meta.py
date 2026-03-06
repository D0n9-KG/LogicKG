from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_canonical_meta(md_path: str) -> dict[str, Any]:
    """
    If md_path is within backend/storage/papers/doi/<...>/source.md, read meta.json.
    Returns {} if missing/unreadable.
    """
    try:
        p = Path(md_path).resolve()
        parent = p.parent
        meta = parent / "meta.json"
        if not meta.exists():
            return {}
        data = json.loads(meta.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

