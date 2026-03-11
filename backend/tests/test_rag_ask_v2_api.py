from fastapi.testclient import TestClient

from app.main import app
from app.rag.models import AskV2Request, AskV2Response


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


def test_ask_v2_response_accepts_community_structured_evidence_payload():
    response = AskV2Response(
        answer="ok",
        structured_evidence=[
            {
                "kind": "community",
                "source_id": "gc:demo",
                "community_id": "gc:demo",
                "text": "Finite element stability community.",
                "member_ids": ["cl-1", "ke-1"],
                "member_kinds": ["Claim", "KnowledgeEntity"],
                "keyword_texts": ["finite element", "stability"],
            }
        ],
    )

    assert response.structured_evidence[0].kind == "community"
    assert response.structured_evidence[0].community_id == "gc:demo"
    assert response.structured_evidence[0].member_ids == ["cl-1", "ke-1"]
