from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.graph.neo4j_client import Neo4jClient
from app.ingest.textbook_identity import infer_textbook_identity
from app.ingest.textbook_upload_store import (
    load_textbook_manifest,
    save_textbook_scan,
    textbook_assembled_root,
    textbook_extracted_root,
)
from app.settings import settings


@dataclass
class DetectedTextbookUnit:
    unit_id: str
    unit_rel_dir: str
    main_md_rel_path: str
    title: str
    textbook_id: str
    asset_count: int
    content_fingerprint: str
    status: str = "ready"
    error: str | None = None
    existing_textbook_id: str | None = None


def _directory_md_counts(root: Path) -> dict[Path, int]:
    counts: dict[Path, int] = {root.resolve(): 0}
    markdown_files = [path for path in root.rglob("*.md") if path.is_file()]
    for md_path in markdown_files:
        current = md_path.parent.resolve()
        while True:
            counts[current] = counts.get(current, 0) + 1
            if current == root.resolve():
                break
            current = current.parent
    return counts


def _subtree_file_count(directory: Path) -> int:
    return sum(1 for path in directory.rglob("*") if path.is_file())


def _has_payload_outside_child(parent: Path, child: Path) -> bool:
    for entry in parent.iterdir():
        if entry.resolve() == child.resolve():
            continue
        if entry.is_file():
            if entry.suffix.lower() != ".md":
                return True
            continue
        if entry.is_dir() and _subtree_file_count(entry) > 0:
            return True
    return False


def _candidate_directory_for_markdown(root: Path, md_path: Path, counts: dict[Path, int]) -> Path:
    root_resolved = root.resolve()
    current = md_path.parent.resolve()
    while current != root_resolved:
        parent = current.parent
        if not parent.is_relative_to(root_resolved):
            break
        if counts.get(parent, 0) != 1:
            break
        if not _has_payload_outside_child(parent, current):
            break
        current = parent
    return current


def _candidate_directories(root: Path, counts: dict[Path, int]) -> list[Path]:
    root_resolved = root.resolve()
    markdown_files = sorted(path.resolve() for path in root_resolved.rglob("*.md") if path.is_file())
    candidates: dict[Path, Path] = {}
    for md_path in markdown_files:
        candidate = _candidate_directory_for_markdown(root_resolved, md_path, counts)
        if counts.get(candidate, 0) != 1:
            continue
        candidates[candidate] = md_path
    return sorted(candidates, key=lambda path: (len(path.relative_to(root_resolved).parts), path.as_posix()))


def _main_markdown_in_subtree(directory: Path) -> Path:
    markdowns = sorted(path for path in directory.rglob("*.md") if path.is_file())
    if len(markdowns) != 1:
        raise ValueError(f"Expected exactly one markdown file under {directory}, found {len(markdowns)}")
    return markdowns[0]


def detect_textbook_units(root: Path) -> list[DetectedTextbookUnit]:
    root = Path(root)
    if not root.exists():
        return []
    root_resolved = root.resolve()
    counts = _directory_md_counts(root_resolved)
    candidates = _candidate_directories(root_resolved, counts)
    units: list[DetectedTextbookUnit] = []
    for directory in candidates:
        main_md = _main_markdown_in_subtree(directory)
        identity = infer_textbook_identity(main_md)
        unit_rel_dir = directory.relative_to(root_resolved).as_posix() or "."
        main_md_rel_path = main_md.relative_to(root_resolved).as_posix()
        asset_count = sum(1 for path in directory.rglob("*") if path.is_file() and path.suffix.lower() != ".md")
        units.append(
            DetectedTextbookUnit(
                unit_id=main_md_rel_path,
                unit_rel_dir=unit_rel_dir,
                main_md_rel_path=main_md_rel_path,
                title=identity.inferred_title,
                textbook_id=identity.textbook_id,
                asset_count=asset_count,
                content_fingerprint=identity.content_fingerprint,
            )
        )
    return sorted(units, key=lambda unit: unit.unit_rel_dir)


def scan_textbook_upload(upload_id: str) -> dict[str, Any]:
    manifest = load_textbook_manifest(upload_id)
    root = textbook_extracted_root(upload_id) if manifest.mode == "zip" else textbook_assembled_root(upload_id)

    units = detect_textbook_units(root)
    errors: list[dict[str, Any]] = []
    if units:
        try:
            with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
                for unit in units:
                    try:
                        client.get_textbook_detail(unit.textbook_id)
                    except KeyError:
                        continue
                    unit.status = "conflict"
                    unit.existing_textbook_id = unit.textbook_id
        except Exception as exc:  # noqa: BLE001
            errors.append({"error": f"Neo4j check failed: {exc}"})

    payload = {
        "upload_id": upload_id,
        "mode": manifest.mode,
        "root": str(root),
        "units": [asdict(unit) for unit in units],
        "errors": errors,
    }
    save_textbook_scan(upload_id, payload)
    return payload
