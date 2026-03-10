from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

from app.ingest import textbook_pipeline


def test_run_autoyoutu_pipeline_sets_utf8_env(monkeypatch, tmp_path: Path) -> None:
    autoyoutu_dir = tmp_path / "autoyoutu"
    autoyoutu_dir.mkdir(parents=True, exist_ok=True)
    (autoyoutu_dir / "integrated_pipeline.py").write_text("print('ok')", encoding="utf-8")
    chapter_md = tmp_path / "chapter_001.md"
    chapter_md.write_text("# ch1\nbody", encoding="utf-8")
    output_dir = tmp_path / "work"
    output_dir.mkdir(parents=True, exist_ok=True)
    graph_data = output_dir / "graph_data"
    graph_data.mkdir(parents=True, exist_ok=True)
    (graph_data / "graph_latest.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(textbook_pipeline.settings, "autoyoutu_dir", str(autoyoutu_dir), raising=False)

    captured_env: dict[str, str] = {}
    captured_kwargs: dict = {}

    def _fake_run(*args, **kwargs):
        nonlocal captured_env, captured_kwargs
        captured_env = dict(kwargs.get("env") or {})
        captured_kwargs = dict(kwargs)
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    import subprocess

    monkeypatch.setattr(subprocess, "run", _fake_run)

    out = textbook_pipeline._run_autoyoutu_pipeline(chapter_md, output_dir, lambda _: None)
    assert out is not None
    assert out.is_file()
    assert captured_env.get("PYTHONUTF8") == "1"
    assert captured_env.get("PYTHONIOENCODING") == "utf-8"
    assert captured_env.get("MD_OUTPUT_DIR") == str(output_dir / "converted_json")
    assert captured_env.get("LOCAL_TEMP_DIR") == str(output_dir / "graph_data")
    assert captured_env.get("CLEANUP_TEMP_FILES") == "false"
    dataset_name = captured_env.get("DATASET_NAME") or ""
    assert re.fullmatch(r"chapter_001_[0-9a-f]{8}", dataset_name)
    assert captured_kwargs.get("encoding") == "utf-8"
    assert captured_kwargs.get("errors") == "replace"
