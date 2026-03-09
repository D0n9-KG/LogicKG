"""Tests for papers API endpoints (P2-16, P2-17)."""
from __future__ import annotations

import csv
import io
import json
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from app.api.routers.papers import (
    _canonical_dir_for_paper_id,
    _doi_sanitized,
    _export_bibtex,
    _export_csv,
    _bib_escape,
    _safe_rel,
)


# ── _doi_sanitized ──

def test_doi_sanitized_basic():
    assert _doi_sanitized("10.1000/abc") == "10.1000_abc"

def test_doi_sanitized_strips_and_lowercases():
    assert _doi_sanitized("  10.ABC/XYZ  ") == "10.abc_xyz"

def test_doi_sanitized_special_chars():
    assert _doi_sanitized("10.1000/a(b)c") == "10.1000_a_b_c"


# ── _safe_rel ──

def test_safe_rel_normal():
    assert _safe_rel("foo/bar.png") == "foo/bar.png"

def test_safe_rel_backslash():
    assert _safe_rel("foo\\bar.png") == "foo/bar.png"

def test_safe_rel_rejects_absolute():
    with pytest.raises(ValueError):
        _safe_rel("/etc/passwd")

def test_safe_rel_rejects_dotdot():
    with pytest.raises(ValueError):
        _safe_rel("../secret")

def test_safe_rel_rejects_empty():
    with pytest.raises(ValueError):
        _safe_rel("")

def test_safe_rel_rejects_drive_letter():
    with pytest.raises(ValueError):
        _safe_rel("C:/Windows")

def test_safe_rel_rejects_special_chars():
    with pytest.raises(ValueError):
        _safe_rel("foo bar.png")


# ── _canonical_dir_for_paper_id ──

def test_canonical_dir_rejects_non_doi():
    with pytest.raises(FileNotFoundError, match="not found"):
        _canonical_dir_for_paper_id("sha256:abc123")

def test_canonical_dir_not_found():
    with pytest.raises(FileNotFoundError, match="not found"):
        _canonical_dir_for_paper_id("doi:10.9999/nonexistent")


# ── get_paper_content endpoint logic ──

def test_get_paper_content_finds_paper_md():
    """Content endpoint should find and return paper.md."""
    with tempfile.TemporaryDirectory() as tmpdir:
        paper_dir = Path(tmpdir) / "papers" / "doi" / "10.1000_test"
        paper_dir.mkdir(parents=True)
        md_file = paper_dir / "paper.md"
        md_file.write_text("# Test Paper\n\nContent here.", encoding="utf-8")

        with patch("app.api.routers.papers._canonical_dir_for_paper_id", return_value=paper_dir):
            from app.api.routers.papers import get_paper_content
            resp = get_paper_content("doi:10.1000/test")
            assert resp.status_code == 200
            assert b"# Test Paper" in resp.body


def test_get_paper_content_fallback_to_source_md():
    """Should fall back to source.md if paper.md doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        paper_dir = Path(tmpdir) / "papers" / "doi" / "10.1000_test"
        paper_dir.mkdir(parents=True)
        md_file = paper_dir / "source.md"
        md_file.write_text("# Source", encoding="utf-8")

        with patch("app.api.routers.papers._canonical_dir_for_paper_id", return_value=paper_dir):
            from app.api.routers.papers import get_paper_content
            resp = get_paper_content("doi:10.1000/test")
            assert resp.status_code == 200
            assert b"# Source" in resp.body


def test_get_paper_content_prefers_source_md_when_both_exist():
    """Should prefer source.md over paper.md so rendered lines match indexed content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        paper_dir = Path(tmpdir) / "papers" / "doi" / "10.1000_test"
        paper_dir.mkdir(parents=True)
        (paper_dir / "paper.md").write_text("# Paper Version", encoding="utf-8")
        (paper_dir / "source.md").write_text("# Source Version", encoding="utf-8")

        with patch("app.api.routers.papers._canonical_dir_for_paper_id", return_value=paper_dir):
            from app.api.routers.papers import get_paper_content

            resp = get_paper_content("doi:10.1000/test")

            assert resp.status_code == 200
            assert b"# Source Version" in resp.body
            assert b"# Paper Version" not in resp.body


def test_get_paper_content_prefers_exact_indexed_source_path_when_available():
    """Should prefer the exact indexed markdown file recorded in Neo4j."""
    with tempfile.TemporaryDirectory() as tmpdir:
        paper_dir = Path(tmpdir) / "papers" / "doi" / "10.1000_test"
        paper_dir.mkdir(parents=True)
        indexed_md = paper_dir / "indexed-source.md"
        indexed_md.write_text("# Indexed Source Version", encoding="utf-8")
        (paper_dir / "source.md").write_text("# Generic Source Version", encoding="utf-8")

        with patch("app.api.routers.papers._canonical_dir_for_paper_id", return_value=paper_dir):
            with patch(
                "app.api.routers.papers._source_md_file_for_paper_id",
                return_value=indexed_md,
                create=True,
            ):
                from app.api.routers.papers import get_paper_content

                resp = get_paper_content("doi:10.1000/test")

                assert resp.status_code == 200
                assert b"# Indexed Source Version" in resp.body
                assert b"# Generic Source Version" not in resp.body


def test_get_paper_content_no_md_file():
    """Should raise 404 when no markdown file exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        paper_dir = Path(tmpdir) / "papers" / "doi" / "10.1000_test"
        paper_dir.mkdir(parents=True)

        with patch("app.api.routers.papers._canonical_dir_for_paper_id", return_value=paper_dir):
            from fastapi import HTTPException
            from app.api.routers.papers import get_paper_content
            with pytest.raises(HTTPException) as exc_info:
                get_paper_content("doi:10.1000/test")
            assert exc_info.value.status_code == 404


# ── Export helpers ──

_SAMPLE_DETAIL: dict = {
    "paper": {
        "paper_id": "doi:10.1000/test",
        "doi": "10.1000/test",
        "title": "A Test Paper",
        "year": 2024,
        "authors": ["Alice", "Bob"],
    },
    "claims": [
        {"claim_key": "c1", "text": "Claim one", "step_type": "Method", "confidence": 0.9, "kinds": ["Definition", "Comparison"]},
        {"claim_key": "c2", "text": "Claim two", "step_type": "Result", "confidence": 0.8, "kinds": []},
    ],
    "logic_steps": [],
    "outgoing_cites": [],
}


def test_export_bibtex_basic():
    bib = _export_bibtex(_SAMPLE_DETAIL)
    assert "@article{" in bib
    assert "title = {A Test Paper}" in bib
    assert "year = {2024}" in bib
    assert "doi = {10.1000/test}" in bib
    assert "Alice and Bob" in bib


def test_export_bibtex_no_authors():
    detail = {"paper": {"doi": "10.1000/x", "title": "T"}}
    bib = _export_bibtex(detail)
    assert "author" not in bib
    assert "title = {T}" in bib


def test_export_bibtex_empty_paper():
    bib = _export_bibtex({"paper": {}})
    assert "@article{unknown," in bib
    assert "title = {Untitled}" in bib


def test_export_csv_basic():
    text = _export_csv(_SAMPLE_DETAIL)
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    assert rows[0] == ["claim_key", "text", "step_type", "confidence", "kinds"]
    assert len(rows) == 3  # header + 2 claims
    assert rows[1][0] == "c1"
    assert rows[1][4] == "Definition;Comparison"
    assert rows[2][0] == "c2"
    assert rows[2][4] == ""


def test_export_csv_no_claims():
    text = _export_csv({"paper": {}, "claims": []})
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    assert len(rows) == 1  # header only


# ── _bib_escape ──

def test_bib_escape_braces_and_backslash():
    assert _bib_escape("a{b}c") == "a\\{b\\}c"
    assert _bib_escape("x\\y") == "x\\\\y"

def test_bib_escape_newline():
    assert _bib_escape("line1\nline2") == "line1 line2"

def test_bib_escape_plain_text():
    assert _bib_escape("Hello World") == "Hello World"

def test_export_bibtex_escapes_special_chars():
    """BibTeX output should escape braces/newlines in title and authors."""
    detail = {"paper": {"doi": "10.1/x", "title": "A {B} Title\nMore", "authors": ["O'Brien"]}}
    bib = _export_bibtex(detail)
    assert "A \\{B\\} Title More" in bib
    assert "O'Brien" in bib
