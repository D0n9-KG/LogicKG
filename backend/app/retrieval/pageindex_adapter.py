from __future__ import annotations

from pathlib import Path
from typing import Any

from app.settings import settings


class PageIndexAdapter:
    """Optional adapter for PageIndex retrieval.

    This adapter is intentionally lightweight in phase-1: it only checks if a
    local index path exists and provides a safe `retrieve` stub. Service logic
    always falls back to existing hybrid retrieval if this adapter is not ready.
    """

    def __init__(self, index_dir: str | None = None):
        configured = (index_dir or settings.pageindex_index_dir or "").strip()
        self.index_dir = Path(configured).expanduser() if configured else None

    def is_available(self) -> bool:
        return bool(self.index_dir and self.index_dir.exists())

    def retrieve(
        self,
        question: str,
        *,
        k: int,
        allowed_sources: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not self.is_available():
            raise RuntimeError("PageIndex adapter unavailable")

        # Placeholder behavior: adapter wiring exists, but retrieval is optional.
        # Returning empty keeps fallback path deterministic and safe.
        _ = (question, k, allowed_sources)
        return []
