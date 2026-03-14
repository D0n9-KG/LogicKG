from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.ingest.upload_actions import keep_existing
from app.ingest.upload_store import assembled_root, manifest_path, scan_path
from app.settings import settings


class KeepExistingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_storage_dir = settings.storage_dir
        self._tmpdir = tempfile.mkdtemp(prefix="logickg-keep-existing-")
        settings.storage_dir = self._tmpdir

    def tearDown(self) -> None:
        settings.storage_dir = self._old_storage_dir
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_manifest(self, upload_id: str) -> None:
        p = manifest_path(upload_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "upload_id": upload_id,
                    "mode": "folder",
                    "chunk_bytes": 1024 * 1024,
                    "files": [],
                    "doi_strategy": "title_crossref",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_scan(self, upload_id: str) -> None:
        p = scan_path(upload_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "upload_id": upload_id,
                    "mode": "folder",
                    "doi_strategy": "title_crossref",
                    "root": str(assembled_root(upload_id)),
                    "units": [
                        {
                            "unit_id": "paperA/paper.md",
                            "unit_rel_dir": "paperA",
                            "md_rel_path": "paperA/paper.md",
                            "doi": "10.1000/a",
                            "title": "Paper A",
                            "year": 2024,
                            "paper_type": "research",
                            "status": "conflict",
                            "error": None,
                            "existing_paper_id": "doi:10.1000/a",
                        },
                        {
                            "unit_id": "paperB/paper.md",
                            "unit_rel_dir": "paperB",
                            "md_rel_path": "paperB/paper.md",
                            "doi": "10.1000/b",
                            "title": "Paper B",
                            "year": 2025,
                            "paper_type": "research",
                            "status": "ready",
                            "error": None,
                            "existing_paper_id": None,
                        },
                    ],
                    "errors": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_staged_unit(self, upload_id: str, rel_dir: str) -> Path:
        unit_dir = assembled_root(upload_id) / rel_dir
        (unit_dir / "images").mkdir(parents=True, exist_ok=True)
        (unit_dir / "paper.md").write_text("# demo\n", encoding="utf-8")
        (unit_dir / "images" / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return unit_dir

    def test_keep_existing_uses_cached_scan_without_full_rescan(self) -> None:
        upload_id = "u_keep_existing"
        self._write_manifest(upload_id)
        self._write_scan(upload_id)
        removed_dir = self._write_staged_unit(upload_id, "paperA")
        kept_dir = self._write_staged_unit(upload_id, "paperB")

        with patch("app.ingest.upload_actions.scan_upload", side_effect=AssertionError("unexpected rescan")):
            out = keep_existing(upload_id, "paperA/paper.md")

        self.assertFalse(removed_dir.exists())
        self.assertTrue(kept_dir.exists())
        self.assertEqual([u.get("unit_id") for u in out.get("units") or []], ["paperB/paper.md"])

        persisted = json.loads(scan_path(upload_id).read_text(encoding="utf-8"))
        self.assertEqual([u.get("unit_id") for u in persisted.get("units") or []], ["paperB/paper.md"])


if __name__ == "__main__":
    unittest.main()
