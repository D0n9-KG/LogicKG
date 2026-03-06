from fastapi.testclient import TestClient

from app.main import app


def test_ask_v2_endpoint_exists():
    c = TestClient(app)
    r = c.post("/rag/ask_v2", json={"question": "q", "k": 3})
    assert r.status_code != 404
