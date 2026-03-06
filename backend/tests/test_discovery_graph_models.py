from app.discovery.models import ResearchQuestionCandidate


def test_candidate_requires_support_evidence_ids():
    c = ResearchQuestionCandidate(
        candidate_id="rq:1",
        question="How does contact friction alter clustering transition?",
        support_evidence_ids=["E1"],
        challenge_evidence_ids=[],
    )
    assert c.support_evidence_ids
