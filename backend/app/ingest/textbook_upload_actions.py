from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Callable

from app.ingest.scan_textbook_upload import scan_textbook_upload
from app.ingest.textbook_pipeline import ingest_textbook
from app.ingest.textbook_upload_store import (
    load_textbook_manifest,
    load_textbook_scan,
    save_textbook_scan,
    textbook_assembled_root,
    textbook_extracted_root,
)
from app.ingest.upload_store import safe_relpath


ProgressFn = Callable[[str, float, str | None], None]
LogFn = Callable[[str], None]


def staging_root(upload_id: str) -> Path:
    manifest = load_textbook_manifest(upload_id)
    return textbook_extracted_root(upload_id) if manifest.mode == 'zip' else textbook_assembled_root(upload_id)


def _load_or_scan(upload_id: str) -> dict[str, Any]:
    try:
        return load_textbook_scan(upload_id)
    except FileNotFoundError:
        return scan_textbook_upload(upload_id)


def _find_unit(scan: dict[str, Any], unit_id: str) -> dict[str, Any] | None:
    units = list(scan.get('units') or [])
    return next((unit for unit in units if str(unit.get('unit_id') or '') == unit_id), None)


def _mark_unit(scan: dict[str, Any], unit_id: str, *, status: str, error: str | None = None) -> dict[str, Any]:
    updated = dict(scan)
    units = []
    matched = False
    for unit in list(scan.get('units') or []):
        next_unit = dict(unit)
        if str(next_unit.get('unit_id') or '') == unit_id:
            next_unit['status'] = status
            next_unit['error'] = error
            matched = True
        units.append(next_unit)
    if not matched:
        raise FileNotFoundError(f'Unit not found: {unit_id}')
    updated['units'] = units
    return updated


def _resolve_main_md_path(upload_id: str, unit: dict[str, Any]) -> Path:
    rel_path = safe_relpath(str(unit.get('main_md_rel_path') or ''))
    md_path = staging_root(upload_id) / rel_path
    if not md_path.is_file():
        raise FileNotFoundError(f'Staged textbook markdown not found: {rel_path}')
    return md_path


def _delete_staged_unit(upload_id: str, unit: dict[str, Any]) -> None:
    root = staging_root(upload_id).resolve()
    rel_dir = safe_relpath(str(unit.get('unit_rel_dir') or '.')) if str(unit.get('unit_rel_dir') or '').strip() != '.' else '.'
    target = root if rel_dir == '.' else (root / rel_dir)
    target = target.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError('Refuse to delete path outside textbook staging root') from exc
    if target == root:
        shutil.rmtree(target, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        return
    shutil.rmtree(target, ignore_errors=True)


def skip_textbook_unit(upload_id: str, unit_id: str) -> dict[str, Any]:
    scan = _load_or_scan(upload_id)
    updated = _mark_unit(scan, unit_id, status='skipped')
    save_textbook_scan(upload_id, updated)
    return updated


def commit_ready_textbook_units(upload_id: str) -> list[dict[str, Any]]:
    scan = _load_or_scan(upload_id)
    ready_units: list[dict[str, Any]] = []
    for unit in list(scan.get('units') or []):
        if str(unit.get('status') or '') != 'ready':
            continue
        ready_units.append(dict(unit))
    return ready_units


def ingest_textbook_upload_ready(
    upload_id: str,
    progress: ProgressFn | None = None,
    log: LogFn | None = None,
) -> dict[str, Any]:
    def notify(stage: str, p: float, msg: str | None = None) -> None:
        if progress:
            progress(stage, p, msg)

    def write_log(line: str) -> None:
        if log:
            log(line)

    scan = _load_or_scan(upload_id)
    ready_units = commit_ready_textbook_units(upload_id)
    if not ready_units:
        return {'ok': True, 'upload_id': upload_id, 'ingested_count': 0, 'failed_count': 0, 'items': []}

    items: list[dict[str, Any]] = []
    updated_scan = dict(scan)
    updated_scan['units'] = [dict(unit) for unit in list(scan.get('units') or [])]
    total = max(1, len(ready_units))
    ingested_count = 0
    failed_count = 0

    for index, unit in enumerate(ready_units, start=1):
        staged_main_md_path = _resolve_main_md_path(upload_id, unit)
        title = str(unit.get('title') or '').strip() or staged_main_md_path.stem
        notify('textbook_upload:ingest', 0.05 + 0.9 * (index - 1) / total, f'导入教材 {title}')
        try:
            result = ingest_textbook(
                str(staged_main_md_path),
                {'title': title},
                progress=progress,
                log=log,
            )
            ingested_count += 1
            items.append(
                {
                    'unit_id': unit['unit_id'],
                    'status': 'ingested',
                    'textbook_id': result.get('textbook_id') or unit.get('textbook_id'),
                    'result': result,
                }
            )
            updated_scan = _mark_unit(updated_scan, str(unit['unit_id']), status='imported')
            _delete_staged_unit(upload_id, unit)
            write_log(f"ingested textbook unit {unit['unit_id']} -> {result.get('textbook_id')}")
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            items.append({'unit_id': unit['unit_id'], 'status': 'failed', 'error': str(exc)})
            updated_scan = _mark_unit(updated_scan, str(unit['unit_id']), status='error', error=str(exc))
            write_log(f"FAILED textbook unit {unit['unit_id']}: {exc}")

    notify('textbook_upload:done', 1.0, '教材批量导入完成')
    save_textbook_scan(upload_id, updated_scan)
    return {
        'ok': failed_count == 0,
        'upload_id': upload_id,
        'ingested_count': ingested_count,
        'failed_count': failed_count,
        'items': items,
    }
