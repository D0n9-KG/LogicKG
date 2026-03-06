from __future__ import annotations

import unittest

from app.evolution.inference import infer_relation_type


class EvolutionInferenceTests(unittest.TestCase):
    def test_identical_claims_are_merge(self) -> None:
        out = infer_relation_type(
            source_text="The model reduces error by 10%.",
            target_text="The model reduces error by 10%.",
            similarity=0.99,
            target_confidence=0.90,
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["event_type"], "MERGE")
        self.assertEqual(out["status"], "accepted")
        self.assertEqual(out.get("reason"), "text_identity")

    def test_supersede_marker_prefers_supersedes(self) -> None:
        out = infer_relation_type(
            source_text="Method A improves robustness.",
            target_text="Method B significantly improve and outperforms Method A on all datasets.",
            similarity=0.95,
            target_confidence=0.90,
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["event_type"], "SUPERSEDES")

    def test_low_similarity_returns_none(self) -> None:
        out = infer_relation_type(
            source_text="Method A improves robustness.",
            target_text="This section lists dataset preprocessing details.",
            similarity=0.22,
            target_confidence=0.90,
        )
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
