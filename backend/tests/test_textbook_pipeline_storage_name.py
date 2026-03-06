from __future__ import annotations

from app.ingest import textbook_pipeline


def test_textbook_storage_name_sanitizes_colon_for_windows() -> None:
    storage_name = textbook_pipeline._textbook_storage_name("tb:729adb31175f10e4fe53da22")
    assert storage_name == "tb_729adb31175f10e4fe53da22"
    assert ":" not in storage_name


def test_textbook_storage_name_keeps_safe_characters() -> None:
    assert textbook_pipeline._textbook_storage_name("tb_abc123") == "tb_abc123"
