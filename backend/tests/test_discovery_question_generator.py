from app.discovery.question_generator import _default_question


def test_default_question_seed_has_no_ellipsis_for_long_description():
    gap = {
        "gap_id": "gap:test:long",
        "gap_type": "seed",
        "description": "Granular flow mechanism under varying boundary conditions with coupled frictional and geometric effects " * 20,
    }
    question = _default_question(gap, variant=1)
    assert "..." not in question
    assert question.endswith("?")
    assert " do not?" not in question.lower()


def test_default_question_seed_uses_diverse_opening_phrases():
    questions = [
        _default_question(
            {
                "gap_id": f"gap:test:{i}",
                "gap_type": "seed",
                "description": "particle segregation dynamics in rotating drums",
            },
            variant=1,
        )
        for i in range(12)
    ]
    starts = {" ".join(q.split()[:4]) for q in questions}
    assert len(starts) >= 2


def test_default_question_prefers_description_over_generic_title():
    gap = {
        "gap_id": "gap:test:generic-title",
        "gap_type": "seed",
        "title": "Gap signal from claim",
        "description": "particle-resolved mechanism of shear localization under dense regime",
    }
    question = _default_question(gap, variant=1)
    assert "signal from claim" not in question.lower()
    assert "shear localization" in question.lower()
