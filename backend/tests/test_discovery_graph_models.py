import pytest
from pydantic import ValidationError

from app.discovery.models import ResearchQuestionCandidate


def test_candidate_requires_support_evidence_ids():
    c = ResearchQuestionCandidate(
        candidate_id="rq:1",
        question="How does contact friction alter clustering transition?",
        support_evidence_ids=["E1"],
        challenge_evidence_ids=[],
    )
    assert c.support_evidence_ids


def test_candidate_rejects_legacy_challenged_proposition_gap_type():
    with pytest.raises(ValidationError):
        ResearchQuestionCandidate(
            candidate_id="rq:legacy",
            question="How can we stabilize a challenged proposition?",
            gap_type="challenged_proposition",
            support_evidence_ids=["E1"],
            challenge_evidence_ids=[],
        )
