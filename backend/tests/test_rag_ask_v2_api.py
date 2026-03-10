from fastapi.testclient import TestClient

from app.main import app
from app.rag.models import AskV2Request


def test_ask_v2_endpoint_exists():
    assert any(
        getattr(route, "path", None) == "/rag/ask_v2" and "POST" in getattr(route, "methods", set())
        for route in app.routes
    )


def test_ask_v2_request_accepts_conversation_payload():
    req = AskV2Request(
        question="How does it compare?",
        conversation=[
            {"question": "What method is used?", "answer": "The paper uses FEM."},
            {"question": "What does it improve?", "answer": "It improves stability."},
        ],
    )

    assert len(req.conversation) == 2
    assert req.conversation[0].question == "What method is used?"
    assert req.conversation[0].answer == "The paper uses FEM."
