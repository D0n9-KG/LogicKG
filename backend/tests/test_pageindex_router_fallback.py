from app.rag.tree_router import route_query


def test_route_query_falls_back_when_pageindex_unavailable():
    r = route_query("granular temperature", pageindex_enabled=False)
    assert r["mode"] == "fallback"
