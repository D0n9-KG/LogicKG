from __future__ import annotations

import json
import re
import unittest
from unittest.mock import patch

from app.llm.citation_purpose import classify_citation_purposes_batch


class CitationPurposeRulesTests(unittest.TestCase):
    def test_batch_applies_context_and_batch_limits_from_rules(self) -> None:
        seen_payload: dict[str, object] = {}

        def fake_call_json(system: str, user: str) -> dict:
            m = re.search(r"Input JSON:\n(.*?)\n\nOutput JSON schema:", user, flags=re.S)
            self.assertIsNotNone(m)
            payload = json.loads(str(m.group(1)))
            seen_payload.update(payload)
            return {"cites": []}

        cites = [
            {
                "cited_paper_id": "doi:10.1/abc",
                "cited_title": "A",
                "contexts": [
                    "0123456789" * 30,
                    "second context should be removed",
                ],
            },
            {
                "cited_paper_id": "doi:10.1/def",
                "cited_title": "B",
                "contexts": ["this cite should be trimmed by max batch"],
            },
        ]
        rules = {
            "citation_purpose_max_contexts_per_cite": 1,
            "citation_purpose_max_context_chars": 120,
            "citation_purpose_max_cites_per_batch": 1,
        }

        with patch("app.llm.citation_purpose.call_json", side_effect=fake_call_json):
            classify_citation_purposes_batch(
                citing_title="Paper",
                cites=cites,
                rules=rules,
            )

        payload_cites = (seen_payload.get("cites") or [])
        self.assertEqual(len(payload_cites), 1)
        only = payload_cites[0]
        self.assertEqual(only["cited_paper_id"], "doi:10.1/abc")
        self.assertEqual(len(only["contexts"]), 1)
        self.assertLessEqual(len(only["contexts"][0]), 120)

    def test_batch_applies_fallback_score_and_max_labels(self) -> None:
        def fake_call_json(system: str, user: str) -> dict:
            return {
                "cites": [
                    {
                        "cited_paper_id": "doi:10.1/abc",
                        "labels": ["MethodUse", "Background", "Survey"],
                        "scores": ["oops", 0.1, 0.9],
                    }
                ]
            }

        with patch("app.llm.citation_purpose.call_json", side_effect=fake_call_json):
            out = classify_citation_purposes_batch(
                citing_title="Paper",
                cites=[{"cited_paper_id": "doi:10.1/abc", "contexts": ["ctx"]}],
                rules={
                    "citation_purpose_fallback_score": 0.25,
                    "citation_purpose_max_labels_per_cite": 2,
                },
            )

        row = out["by_id"]["doi:10.1/abc"]
        self.assertEqual(row["labels"], ["Survey", "MethodUse"])
        self.assertEqual(row["scores"], [0.9, 0.25])


if __name__ == "__main__":
    unittest.main()
