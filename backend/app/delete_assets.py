from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.graph.neo4j_client import Neo4jClient
from app.ingest.textbook_pipeline import _textbook_storage_name
from app.settings import settings


_DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _storage_root() -> Path:
    root = _backend_root() / settings.storage_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _doi_sanitized(doi: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", doi.strip().lower())


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _append_log(paper: dict[str, Any], line: str) -> dict[str, Any]:
    log = list(paper.get("edit_log") or [])
    log.append(line)
    if len(log) > 200:
        log = log[-200:]
    return {"edit_log": log}


def _safe_rmtree(path: Path, allowed_root: Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_root = allowed_root.resolve()
        resolved_path.relative_to(resolved_root)
    except Exception:
        return False
    if not resolved_path.exists() or not resolved_path.is_dir():
        return False
    try:
        shutil.rmtree(resolved_path, ignore_errors=True)
        return True
    except Exception:
        return False


def delete_paper_asset(paper_id: str, hard_delete: bool = True) -> dict[str, Any]:
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        client.ensure_schema()
        paper = client.get_paper_basic(paper_id)
        if not bool(paper.get("ingested")):
            return {
                "ok": True,
                "paper_id": paper_id,
                "status": "skipped",
                "skipped": True,
                "reason": "metadata_only",
                "hard_delete": bool(hard_delete),
                "removed": {"canonical_dir": False, "derived_dir": False},
            }

        client.delete_paper_subgraph(paper_id)
        try:
            client.remove_paper_from_all_collections(paper_id)
        except Exception:
            pass

        if hard_delete:
            client.delete_paper_node(paper_id)
        else:
            props = {
                "ingested": False,
                "source_md_path": "",
                "storage_dir": None,
                "review_pending_task_id": None,
                "review_resolved_task_id": None,
                "human_meta_json": _dump({}),
                "human_meta_cleared_json": _dump([]),
                "human_logic_json": _dump({}),
                "human_logic_cleared_json": _dump([]),
                "human_claims_json": _dump({}),
                "human_claims_cleared_json": _dump([]),
                "human_cites_purpose_json": _dump({}),
                "human_cites_purpose_cleared_json": _dump([]),
                "deleted_at": _utc_now_iso(),
                "deleted_reason": "user_deleted",
            }
            props.update(_append_log(paper, "paper:delete:user_deleted"))
            client.update_paper_props(paper_id, props)

    storage = _storage_root()
    removed = {"canonical_dir": False, "derived_dir": False}
    storage_dir = str(paper.get("storage_dir") or "").strip()

    if storage_dir:
        removed["canonical_dir"] = _safe_rmtree(Path(storage_dir), allowed_root=storage / "papers" / "doi")
    else:
        doi = str(paper.get("doi") or "").strip().lower()
        if not doi and paper_id.startswith("doi:"):
            doi = paper_id[4:]
        if doi and _DOI_RE.match(doi):
            canonical_dir = storage / "papers" / "doi" / _doi_sanitized(doi)
            removed["canonical_dir"] = _safe_rmtree(canonical_dir, allowed_root=storage / "papers" / "doi")

    derived_dir = storage / "derived" / "papers" / _safe_id(paper_id)
    removed["derived_dir"] = _safe_rmtree(derived_dir, allowed_root=storage / "derived" / "papers")

    return {
        "ok": True,
        "paper_id": paper_id,
        "status": "deleted",
        "skipped": False,
        "hard_delete": bool(hard_delete),
        "removed": removed,
    }


def delete_textbook_asset(textbook_id: str) -> dict[str, Any]:
    with Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password) as client:
        detail = client.get_textbook_detail(textbook_id)
        delete_result = client.delete_textbook(textbook_id)

    storage = _storage_root()
    artifact_dir = storage / "textbooks" / _textbook_storage_name(textbook_id)
    removed = {
        "artifact_dir": _safe_rmtree(artifact_dir, allowed_root=storage / "textbooks"),
        "source_dir": False,
    }

    return {
        "ok": True,
        "textbook_id": textbook_id,
        "status": "deleted",
        "skipped": False,
        "removed": removed,
        "source_dir": str(detail.get("source_dir") or "").strip() or None,
        **delete_result,
    }
