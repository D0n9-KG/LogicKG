from app.discovery.feedback_service import apply_feedback


def test_feedback_updates_candidate_quality_score():
    updated = apply_feedback(candidate_id="rq:1", label="accepted", note="well-grounded")
    assert "updated_score" in updated
