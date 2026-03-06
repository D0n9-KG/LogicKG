from __future__ import annotations

import shutil
import tempfile
import unittest

from app.schema_store import create_new_version, delete_version, list_versions, load_active
from app.settings import settings


class SchemaVersionNamesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_storage_dir = settings.storage_dir
        self._tmpdir = tempfile.mkdtemp(prefix="logickg-schema-names-")
        settings.storage_dir = self._tmpdir

    def tearDown(self) -> None:
        settings.storage_dir = self._old_storage_dir
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_version_name_is_saved_and_listed(self) -> None:
        base = load_active("research")
        base["name"] = "高精度-实验"
        saved = create_new_version("research", base, activate=True)
        self.assertEqual(str(saved.get("name") or ""), "高精度-实验")

        versions = list_versions("research")
        self.assertTrue(versions)
        newest = versions[0]
        self.assertEqual(newest.version, int(saved.get("version") or 0))
        self.assertEqual(newest.name, "高精度-实验")

    def test_delete_inactive_version_keeps_active_version(self) -> None:
        base = load_active("research")
        v2 = create_new_version("research", {**base, "name": "v2"}, activate=True)
        _ = create_new_version("research", {**base, "name": "v3"}, activate=True)
        out = delete_version("research", int(v2.get("version") or 2))
        self.assertEqual(out.get("deleted_version"), int(v2.get("version") or 2))
        self.assertFalse(bool(out.get("active_changed")))
        self.assertEqual(int(out.get("active_version") or 0), 3)

    def test_delete_active_version_auto_switches_to_latest_remaining(self) -> None:
        base = load_active("research")
        _ = create_new_version("research", {**base, "name": "v2"}, activate=True)
        v3 = create_new_version("research", {**base, "name": "v3"}, activate=True)
        out = delete_version("research", int(v3.get("version") or 3))
        self.assertEqual(out.get("deleted_version"), int(v3.get("version") or 3))
        self.assertTrue(bool(out.get("active_changed")))
        self.assertEqual(int(out.get("active_version") or 0), 2)

    def test_delete_last_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "last schema version"):
            delete_version("research", 1)


if __name__ == "__main__":
    unittest.main()
