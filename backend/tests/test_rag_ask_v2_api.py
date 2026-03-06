from fastapi.testclient import TestClient

from app.main import app


def test_ask_v2_endpoint_exists():
    assert any(
        getattr(route, "path", None) == "/rag/ask_v2" and "POST" in getattr(route, "methods", set())
        for route in app.routes
    )
