from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.routers.textbooks as textbooks_router


def _build_client() -> TestClient:
    app = FastAPI()
    app.include_router(textbooks_router.router)
    return TestClient(app)


def test_textbook_upload_skip_endpoint_returns_updated_scan(monkeypatch) -> None:
    monkeypatch.setattr(
        textbooks_router,
        'skip_textbook_unit',
        lambda upload_id, unit_id: {
            'upload_id': upload_id,
            'units': [{'unit_id': unit_id, 'status': 'skipped'}],
            'errors': [],
        },
    )

    client = _build_client()
    response = client.post('/textbooks/upload/skip', json={'upload_id': 'tb-upload-1', 'unit_id': 'book-a/main.md'})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['upload_id'] == 'tb-upload-1'
    assert payload['units'][0]['status'] == 'skipped'


def test_textbook_upload_commit_ready_submits_batch_task(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_submit(task_type, payload):
        captured['task_type'] = task_type
        captured['payload'] = dict(payload)
        return 'task-textbook-upload-1'

    monkeypatch.setattr(textbooks_router.task_manager, 'submit', _fake_submit)

    client = _build_client()
    response = client.post('/textbooks/upload/commit_ready', json={'upload_id': 'tb-upload-1'})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload == {
        'task_id': 'task-textbook-upload-1',
        'task_type': 'ingest_textbook_upload_ready',
    }
    assert str(getattr(captured['task_type'], 'value', captured['task_type'])) == 'ingest_textbook_upload_ready'
    assert captured['payload'] == {'upload_id': 'tb-upload-1'}


def test_textbook_upload_start_creates_folder_session(monkeypatch) -> None:
    monkeypatch.setattr(textbooks_router, 'new_textbook_upload_id', lambda: 'tb-upload-start')

    client = _build_client()
    response = client.post(
        '/textbooks/upload/start',
        json={
            'mode': 'folder',
            'chunk_bytes': 262144,
            'files': [{'path': 'books/book-a/main.md', 'size': 120}],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload == {'upload_id': 'tb-upload-start', 'chunk_bytes': 262144}


def test_textbook_upload_finish_returns_scan(monkeypatch) -> None:
    monkeypatch.setattr(
        textbooks_router,
        'scan_textbook_upload',
        lambda upload_id: {
            'upload_id': upload_id,
            'units': [{'unit_id': 'book-a/main.md', 'status': 'ready'}],
            'errors': [],
        },
    )
    monkeypatch.setattr(
        textbooks_router,
        'load_textbook_manifest',
        lambda upload_id: type('Manifest', (), {'mode': 'folder', 'files': [], 'chunk_bytes': 1024, 'total_chunks': None})(),
    )

    client = _build_client()
    response = client.post('/textbooks/upload/finish', params={'upload_id': 'tb-upload-finish'})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload['upload_id'] == 'tb-upload-finish'
    assert payload['units'][0]['status'] == 'ready'
