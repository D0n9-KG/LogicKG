from __future__ import annotations

from app.ingest.textbook_upload_store import (
    TextbookUploadManifest,
    save_textbook_manifest,
    save_textbook_scan,
)
import pytest


def _save_prepared_upload(upload_id: str) -> None:
    save_textbook_manifest(TextbookUploadManifest(upload_id=upload_id, mode='folder', chunk_bytes=1024))
    save_textbook_scan(
        upload_id,
        {
            'upload_id': upload_id,
            'mode': 'folder',
            'units': [
                {
                    'unit_id': 'book-a/main.md',
                    'unit_rel_dir': 'book-a',
                    'main_md_rel_path': 'book-a/main.md',
                    'title': '教材 A',
                    'textbook_id': 'tb:a',
                    'asset_count': 1,
                    'status': 'ready',
                },
                {
                    'unit_id': 'book-b/main.md',
                    'unit_rel_dir': 'book-b',
                    'main_md_rel_path': 'book-b/main.md',
                    'title': '教材 B',
                    'textbook_id': 'tb:b',
                    'asset_count': 0,
                    'status': 'conflict',
                },
            ],
            'errors': [],
        },
    )


def test_skip_textbook_unit_marks_target_as_skipped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr('app.settings.settings.storage_dir', str(tmp_path / 'storage'))
    from app.ingest.textbook_upload_actions import skip_textbook_unit

    _save_prepared_upload('tb-upload-skip')

    updated = skip_textbook_unit('tb-upload-skip', 'book-a/main.md')

    units = {unit['unit_id']: unit for unit in updated['units']}
    assert units['book-a/main.md']['status'] == 'skipped'
    assert units['book-b/main.md']['status'] == 'conflict'


def test_commit_ready_textbook_units_filters_only_ready_units(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr('app.settings.settings.storage_dir', str(tmp_path / 'storage'))
    from app.ingest.textbook_upload_actions import commit_ready_textbook_units

    _save_prepared_upload('tb-upload-ready')

    ready_units = commit_ready_textbook_units('tb-upload-ready')

    assert len(ready_units) == 1
    assert ready_units[0]['unit_id'] == 'book-a/main.md'
    assert ready_units[0]['status'] == 'ready'


def test_skip_textbook_unit_rejects_missing_unit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr('app.settings.settings.storage_dir', str(tmp_path / 'storage'))
    from app.ingest.textbook_upload_actions import skip_textbook_unit

    _save_prepared_upload('tb-upload-missing')

    with pytest.raises(FileNotFoundError, match='Unit not found'):
        skip_textbook_unit('tb-upload-missing', 'missing.md')
