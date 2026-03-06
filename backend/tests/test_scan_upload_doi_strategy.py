from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.crossref.client import CrossrefResolveResult, CrossrefWork
from app.ingest.scan_upload import scan_upload
from app.ingest.upload_store import assembled_root, manifest_path
from app.settings import settings


class ScanUploadDoiStrategyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_storage_dir = settings.storage_dir
        self._tmpdir = tempfile.mkdtemp(prefix="logickg-doi-strategy-")
        settings.storage_dir = self._tmpdir

    def tearDown(self) -> None:
        settings.storage_dir = self._old_storage_dir
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _write_manifest(self, upload_id: str, doi_strategy: str) -> None:
        p = manifest_path(upload_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "upload_id": upload_id,
                    "mode": "folder",
                    "chunk_bytes": 1024 * 1024,
                    "files": [],
                    "doi_strategy": doi_strategy,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_unit_md(self, upload_id: str, rel_dir: str, md_name: str, content: str) -> None:
        root = assembled_root(upload_id)
        unit_dir = root / rel_dir
        (unit_dir / "images").mkdir(parents=True, exist_ok=True)
        (unit_dir / "images" / "fig1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (unit_dir / md_name).write_text(content, encoding="utf-8")

    @patch("app.ingest.scan_upload.Neo4jClient")
    def test_extract_only_keeps_need_doi_without_doi_line(self, mock_neo4j) -> None:
        upload_id = "u_extract"
        self._write_manifest(upload_id, "extract_only")
        self._write_unit_md(
            upload_id,
            "paperA",
            "paper.md",
            "# A Paper Without DOI\n\nAlice, Bob\n\nBody text.",
        )

        out = scan_upload(upload_id)

        units = out.get("units") or []
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].get("status"), "need_doi")
        self.assertIsNone(units[0].get("doi"))
        mock_neo4j.assert_not_called()

    @patch("app.ingest.scan_upload.Neo4jClient")
    @patch("app.ingest.scan_upload.CrossrefClient")
    def test_title_crossref_resolves_main_doi(self, mock_crossref_cls, mock_neo4j_cls) -> None:
        upload_id = "u_crossref"
        self._write_manifest(upload_id, "title_crossref")
        self._write_unit_md(
            upload_id,
            "paperB",
            "paper.md",
            "# Learning Constitutive Laws\n\nAlice, Bob\n\nBody text.",
        )

        selected = CrossrefWork(
            doi="10.1234/example-doi",
            title="Learning Constitutive Laws",
            year=2025,
            venue="Journal X",
            authors=["Alice", "Bob"],
            score=88.0,
        )
        mock_crossref = mock_crossref_cls.return_value
        mock_crossref.resolve_reference.return_value = CrossrefResolveResult(
            query="Learning Constitutive Laws",
            topk=[selected],
            selected=selected,
            confidence=0.88,
        )

        mock_neo4j = mock_neo4j_cls.return_value.__enter__.return_value
        mock_neo4j.get_paper_basic.side_effect = KeyError("not found")

        out = scan_upload(upload_id)

        units = out.get("units") or []
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].get("status"), "ready")
        self.assertEqual(units[0].get("doi"), "10.1234/example-doi")
        self.assertEqual((out.get("doi_strategy") or ""), "title_crossref")
        mock_crossref.resolve_reference.assert_called_once()


if __name__ == "__main__":
    unittest.main()
