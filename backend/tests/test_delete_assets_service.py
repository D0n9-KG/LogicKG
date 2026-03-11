from __future__ import annotations

from pathlib import Path

import app.delete_assets as delete_assets


class _FakePaperClient:
    def __init__(self, *args, **kwargs) -> None:
        self.called_delete_subgraph = False
        self.called_remove_collections = False
        self.called_delete_node = False
        self.called_update_props = False
        self.paper = {
            "paper_id": "doi:10.1234/stub",
            "ingested": False,
            "storage_dir": "",
            "doi": "10.1234/stub",
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


class _FakeTextbookClient:
    def __init__(self, *args, **kwargs) -> None:
        self.deleted = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get_textbook_detail(self, textbook_id: str) -> dict:
        return {
            "textbook_id": textbook_id,
            "title": "Deep Learning",
            "source_dir": "C:/source-md",
            "chapters": [],
        }

    def delete_textbook(self, textbook_id: str) -> dict:
        self.deleted = True
        return {
            "deleted_entities": 4,
            "deleted_chapters": 2,
            "deleted_textbook": 1,
        }


def test_delete_textbook_asset_removes_storage_textbooks_artifacts_only(monkeypatch, tmp_path: Path) -> None:
    fake = _FakeTextbookClient()
    storage_root = tmp_path / "storage"
    artifact_dir = storage_root / "textbooks" / "tb_test"
    artifact_dir.mkdir(parents=True)
    source_dir = tmp_path / "source-md"
    source_dir.mkdir()

    monkeypatch.setattr(delete_assets, "Neo4jClient", lambda *args, **kwargs: fake)
    monkeypatch.setattr(delete_assets, "_storage_root", lambda: storage_root)

    result = delete_assets.delete_textbook_asset("tb:test")

    assert result["removed"]["artifact_dir"] is True
    assert result["removed"]["source_dir"] is False
    assert not artifact_dir.exists()
    assert source_dir.exists()
    assert fake.deleted is True


def test_delete_paper_asset_skips_metadata_only_paper(monkeypatch) -> None:
    fake = _FakePaperClient()
    monkeypatch.setattr(delete_assets, "Neo4jClient", lambda *args, **kwargs: fake)

    result = delete_assets.delete_paper_asset("doi:10.1234/stub")

    assert result["skipped"] is True
    assert result["reason"] == "metadata_only"
    assert fake.called_delete_subgraph is False
    assert fake.called_remove_collections is False
    assert fake.called_delete_node is False
    assert fake.called_update_props is False
