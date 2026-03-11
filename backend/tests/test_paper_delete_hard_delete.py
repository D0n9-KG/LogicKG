from __future__ import annotations

import unittest
from unittest.mock import patch

from app.api.routers.paper_edits import delete_ingested_paper


class PaperDeleteModeTests(unittest.TestCase):
    def test_delete_defaults_to_hard_delete(self) -> None:
        with patch(
            "app.api.routers.paper_edits.delete_paper_asset",
            return_value={"ok": True, "hard_delete": True},
        ) as delete_asset:
            out = delete_ingested_paper("doi:10.1234/test")
        delete_asset.assert_called_once_with("doi:10.1234/test", hard_delete=True)
        self.assertEqual(out.get("hard_delete"), True)

    def test_delete_can_keep_legacy_stub_mode(self) -> None:
        with patch(
            "app.api.routers.paper_edits.delete_paper_asset",
            return_value={"ok": True, "hard_delete": False},
        ) as delete_asset:
            out = delete_ingested_paper("doi:10.1234/test", hard_delete=False)
        delete_asset.assert_called_once_with("doi:10.1234/test", hard_delete=False)
        self.assertEqual(out.get("hard_delete"), False)

    def test_delete_metadata_only_paper_returns_skipped_result(self) -> None:
        with patch(
            "app.api.routers.paper_edits.delete_paper_asset",
            return_value={"ok": True, "skipped": True, "reason": "metadata_only"},
        ) as delete_asset:
            out = delete_ingested_paper("doi:10.1234/test")
        delete_asset.assert_called_once_with("doi:10.1234/test", hard_delete=True)
        self.assertTrue(out.get("skipped"))
        self.assertEqual(out.get("reason"), "metadata_only")


if __name__ == "__main__":
    unittest.main()
