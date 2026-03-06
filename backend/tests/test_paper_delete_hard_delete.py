from __future__ import annotations

import unittest
from unittest.mock import patch

from app.api.routers.paper_edits import delete_ingested_paper


class _FakeNeo4jClient:
    def __init__(self, *args, **kwargs) -> None:
        self.called_delete_subgraph = False
        self.called_remove_collections = False
        self.called_delete_node = False
        self.called_update_props = False
        self.paper = {
            "paper_id": "doi:10.1234/test",
            "ingested": True,
            "storage_dir": "",
            "doi": "",
            "edit_log": [],
        }

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def ensure_schema(self) -> None:
        return None

    def get_paper_basic(self, paper_id: str) -> dict:
        return dict(self.paper)

    def delete_paper_subgraph(self, paper_id: str) -> None:
        self.called_delete_subgraph = True

    def remove_paper_from_all_collections(self, paper_id: str) -> None:
        self.called_remove_collections = True

    def delete_paper_node(self, paper_id: str) -> None:
        self.called_delete_node = True

    def update_paper_props(self, paper_id: str, props: dict) -> None:
        self.called_update_props = True


class PaperDeleteModeTests(unittest.TestCase):
    def test_delete_defaults_to_hard_delete(self) -> None:
        fake = _FakeNeo4jClient()
        with (
            patch("app.api.routers.paper_edits.Neo4jClient", return_value=fake),
            patch("app.api.routers.paper_edits._safe_rmtree", return_value=False),
        ):
            out = delete_ingested_paper("doi:10.1234/test")
        self.assertTrue(fake.called_delete_subgraph)
        self.assertTrue(fake.called_remove_collections)
        self.assertTrue(fake.called_delete_node)
        self.assertFalse(fake.called_update_props)
        self.assertEqual(out.get("hard_delete"), True)

    def test_delete_can_keep_legacy_stub_mode(self) -> None:
        fake = _FakeNeo4jClient()
        with (
            patch("app.api.routers.paper_edits.Neo4jClient", return_value=fake),
            patch("app.api.routers.paper_edits._safe_rmtree", return_value=False),
        ):
            out = delete_ingested_paper("doi:10.1234/test", hard_delete=False)
        self.assertTrue(fake.called_delete_subgraph)
        self.assertTrue(fake.called_remove_collections)
        self.assertFalse(fake.called_delete_node)
        self.assertTrue(fake.called_update_props)
        self.assertEqual(out.get("hard_delete"), False)


if __name__ == "__main__":
    unittest.main()
