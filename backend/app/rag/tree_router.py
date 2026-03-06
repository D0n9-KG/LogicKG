from __future__ import annotations

from app.retrieval.pageindex_adapter import PageIndexAdapter


def route_query(
    query: str,
    *,
    pageindex_enabled: bool,
    adapter: PageIndexAdapter | None = None,
) -> dict[str, str]:
    _ = query
    if not pageindex_enabled:
        return {"mode": "fallback", "reason": "disabled"}

    try:
        probe = adapter or PageIndexAdapter()
        if not probe.is_available():
            return {"mode": "fallback", "reason": "adapter_unavailable"}
        return {"mode": "pageindex", "reason": "adapter_ready"}
    except Exception:
        return {"mode": "fallback", "reason": "adapter_error"}
