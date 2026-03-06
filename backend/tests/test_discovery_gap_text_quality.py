from app.discovery.gap_detector import _from_gap_like_claims, _from_gap_seeds


class _FakeGapClient:
    def __init__(self, claim_rows=None, seed_rows=None):
        self._claim_rows = list(claim_rows or [])
        self._seed_rows = list(seed_rows or [])

    def list_gap_like_claims(self, limit=200, kinds=None):  # noqa: ARG002
        return self._claim_rows[:limit]

    def list_gap_seeds(self, limit=300, kinds=None):  # noqa: ARG002
        return self._seed_rows[:limit]


def test_gap_like_claim_titles_are_humanized_not_signal_labels():
    client = _FakeGapClient(
        claim_rows=[
            {
                "claim_id": "cl:1",
                "text": "Limitation signal from claim",
                "kinds": ["Limitation"],
                "confidence": 0.9,
                "evidence_count": 2,
                "paper_id": "p:1",
                "paper_title": "A Study on Powder Segregation Dynamics",
                "prop_id": "pr:1",
            }
        ]
    )
    out = _from_gap_like_claims(client=client, keywords=[], limit=5)
    assert len(out) == 1
    row = out[0]
    assert "signal from claim" not in str(row.get("title") or "").lower()
    assert "the issue appears in" in str(row.get("description") or "").lower()
    assert "powder segregation" in str(row.get("description") or "").lower()


def test_gap_seed_titles_are_humanized_and_description_keeps_real_text():
    client = _FakeGapClient(
        seed_rows=[
            {
                "seed_id": "gs:1",
                "claim_id": "cl:2",
                "text": "Current methods cannot capture particle-scale contact anisotropy under dense packing.",
                "kinds": ["Gap"],
                "confidence": 0.8,
                "paper_id": "p:2",
                "paper_title": "Dense Regime Contact Anisotropy Analysis",
                "prop_id": "pr:2",
            }
        ]
    )
    out = _from_gap_seeds(client=client, keywords=[], limit=5)
    assert len(out) == 1
    row = out[0]
    assert "signal from extracted gap seed" not in str(row.get("title") or "").lower()
    assert "particle-scale contact anisotropy" in str(row.get("description") or "").lower()
