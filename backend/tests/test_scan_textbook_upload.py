from pathlib import Path

from app.ingest.scan_textbook_upload import detect_textbook_units, scan_textbook_upload
from app.ingest.textbook_upload_store import (
    TextbookUploadFileEntry,
    TextbookUploadManifest,
    load_textbook_scan,
    save_textbook_manifest,
    textbook_assembled_root,
)


def test_detect_textbook_units_finds_multiple_nested_books(tmp_path: Path) -> None:
    root = tmp_path / 'uploads'
    (root / 'set-a' / 'book-1').mkdir(parents=True)
    (root / 'set-b' / 'deep' / 'book-2' / 'images').mkdir(parents=True)
    (root / 'set-a' / 'book-1' / 'main.md').write_text('# Book One\n\nText\n', encoding='utf-8')
    (root / 'set-b' / 'deep' / 'book-2' / 'main.md').write_text('# Book Two\n\nText\n', encoding='utf-8')
    (root / 'set-b' / 'deep' / 'book-2' / 'images' / 'fig-1.png').write_bytes(b'png')

    units = detect_textbook_units(root)

    assert [unit.title for unit in units] == ['Book One', 'Book Two']
    assert [unit.asset_count for unit in units] == [0, 1]


def test_detect_textbook_units_chooses_highest_single_markdown_subtree(tmp_path: Path) -> None:
    root = tmp_path / 'bundle'
    (root / 'library' / 'book-a' / 'assets').mkdir(parents=True)
    (root / 'library' / 'book-a' / 'main.md').write_text('# Book A\n\nText\n', encoding='utf-8')
    (root / 'library' / 'book-a' / 'assets' / 'img.png').write_bytes(b'img')

    units = detect_textbook_units(root)

    assert len(units) == 1
    assert units[0].unit_rel_dir == 'library/book-a'
    assert units[0].main_md_rel_path == 'library/book-a/main.md'
    assert units[0].asset_count == 1


def test_scan_textbook_upload_marks_existing_textbook_as_conflict(tmp_path: Path, monkeypatch) -> None:
    from app.ingest import textbook_upload_store as store
    from app.ingest import scan_textbook_upload as scanner

    storage_root = tmp_path / 'storage'
    monkeypatch.setattr(store.settings, 'storage_dir', str(storage_root), raising=False)
    monkeypatch.setattr(scanner.settings, 'storage_dir', str(storage_root), raising=False)

    manifest = TextbookUploadManifest(
        upload_id='tbscan1',
        mode='folder',
        chunk_bytes=1024,
        files=[TextbookUploadFileEntry(path='library/book-a/main.md', size=16)],
    )
    save_textbook_manifest(manifest)
    root = textbook_assembled_root(manifest.upload_id)
    (root / 'library' / 'book-a').mkdir(parents=True, exist_ok=True)
    (root / 'library' / 'book-a' / 'main.md').write_text('# Book A\n\nText\n', encoding='utf-8')

    class _FakeNeo4jClient:
        def __init__(self, uri: str, user: str, password: str) -> None:
            self.uri = uri
            self.user = user
            self.password = password

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def get_textbook_detail(self, textbook_id: str) -> dict:
            return {'textbook_id': textbook_id}

    monkeypatch.setattr(scanner, 'Neo4jClient', _FakeNeo4jClient)

    scan = scan_textbook_upload(manifest.upload_id)

    assert scan['units'][0]['status'] == 'conflict'
    assert scan['units'][0]['existing_textbook_id'] == scan['units'][0]['textbook_id']
    assert load_textbook_scan(manifest.upload_id)['units'][0]['status'] == 'conflict'
