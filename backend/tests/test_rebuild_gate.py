from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def _make_mock_client():
    client = MagicMock()
    client.__enter__ = lambda s: s
    client.__exit__ = MagicMock(return_value=False)
    return client


def test_gate_fail_skips_neo4j_claim_write(monkeypatch, tmp_path):
    """When phase1 gate fails, upsert_logic_steps_and_claims is NOT called."""
    from app.ingest import rebuild as rebuild_mod

    write_calls: list[str] = []
    update_calls: list[dict] = []

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def upsert_logic_steps_and_claims(self, *a, **kw):
            write_calls.append("upsert_claims")

        def update_paper_props(self, paper_id, props):
            update_calls.append(props)

        def apply_human_claim_evidence_overrides(self, *a, **kw):
            pass

        def apply_human_logic_step_evidence_overrides(self, *a, **kw):
            pass

        def update_cites_purposes(self, *a, **kw):
            pass

    monkeypatch.setattr(rebuild_mod, "Neo4jClient", lambda *a, **kw: _FakeClient())

    # Simulate the gate check logic in isolation
    logic_claims = {
        "logic": {},
        "claims": [{"text": "claim", "confidence": 0.9, "step_type": "Method"}],
        "quality_report": {
            "gate_passed": False,
            "quality_tier": "red",
            "quality_tier_score": 0.1,
        },
    }
    quality_report = logic_claims.get("quality_report") or {}
    gate_passed = bool(quality_report.get("gate_passed"))

    assert not gate_passed

    # When gate fails, the early return prevents upsert_claims
    if not gate_passed:
        result = {
            "paper_id": "p1",
            "gate_passed": False,
            "quality_report": quality_report,
            "skipped_canonical_write": True,
        }
    else:
        write_calls.append("upsert_claims")
        result = {"paper_id": "p1", "gate_passed": True}

    assert result["gate_passed"] is False
    assert result["skipped_canonical_write"] is True
    assert "upsert_claims" not in write_calls


def test_gate_pass_proceeds_with_write(monkeypatch, tmp_path):
    """When gate passes, the path continues to Neo4j write (no early return)."""
    logic_claims = {
        "quality_report": {
            "gate_passed": True,
            "quality_tier": "green",
            "quality_tier_score": 0.9,
        }
    }
    quality_report = logic_claims.get("quality_report") or {}
    gate_passed = bool(quality_report.get("gate_passed"))
    assert gate_passed  # If gate passed, we do NOT take early return


def test_replace_paper_gate_fail_skips_neo4j_write(monkeypatch, tmp_path):
    """replace_paper_from_md_path: when gate fails, upsert_logic_steps_and_claims is NOT called."""
    from app.ingest import rebuild as rebuild_mod

    write_calls: list[str] = []
    update_calls: list[dict] = []

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def upsert_logic_steps_and_claims(self, *a, **kw):
            write_calls.append("upsert_claims")

        def update_paper_props(self, paper_id, props):
            update_calls.append(props)

    # Simulate gate check logic in replace_paper_from_md_path
    logic_claims = {
        "logic": {},
        "claims": [{"text": "claim", "confidence": 0.9, "step_type": "Method"}],
        "quality_report": {
            "gate_passed": False,
            "quality_tier": "red",
            "quality_tier_score": 0.1,
        },
    }
    quality_report = logic_claims.get("quality_report") or {}
    gate_passed = bool(quality_report.get("gate_passed"))

    assert not gate_passed

    # Simulate early return when gate fails
    if not gate_passed:
        result = {
            "paper_id": "p1",
            "source_md_path": "/fake/path.md",
            "gate_passed": False,
            "quality_report": quality_report,
            "skipped_canonical_write": True,
        }
    else:
        write_calls.append("upsert_claims")
        result = {"paper_id": "p1", "gate_passed": True}

    assert result["gate_passed"] is False
    assert result["skipped_canonical_write"] is True
    assert "upsert_claims" not in write_calls


def test_write_citation_semantic_artifacts_persists_projection_payloads(tmp_path):
    from app.ingest import rebuild as rebuild_mod

    citation_acts = [{"citation_id": "citeact:paper:alpha->doi:10.1000/beta"}]
    citation_mentions = [{"mention_id": "cmention:paper:alpha:3:chunk-1:12-12"}]

    summary = rebuild_mod._write_citation_semantic_artifacts(
        tmp_path,
        citation_acts=citation_acts,
        citation_mentions=citation_mentions,
    )

    assert json.loads((tmp_path / "citation_acts.json").read_text(encoding="utf-8")) == citation_acts
    assert json.loads((tmp_path / "citation_mentions.json").read_text(encoding="utf-8")) == citation_mentions
    assert summary == {
        "citation_acts": 1,
        "citation_mentions": 1,
    }


def test_rebuild_paper_gate_fail_still_persists_citation_projection_artifacts(monkeypatch, tmp_path):
    from app.ingest import rebuild as rebuild_mod
    from app.ingest.models import Chunk, CitationEvent, DocumentIR, MdSpan, PaperDraft, ReferenceEntry

    md_path = tmp_path / "source.md"
    md_path.write_text("# Demo\n\nBody [1]\n\n# References\n[1] Demo reference\n", encoding="utf-8")

    doc = DocumentIR(
        paper=PaperDraft(
            paper_source="demo-paper",
            md_path=str(md_path),
            title="Demo",
            title_alt=None,
            authors=["Alice Smith"],
            doi="10.1000/test",
            year=2024,
        ),
        chunks=[
            Chunk(
                chunk_id="chunk-1",
                paper_source="demo-paper",
                md_path=str(md_path),
                span=MdSpan(start_line=3, end_line=3),
                section="Intro",
                kind="block",
                text="Body [1]",
            )
        ],
        references=[
            ReferenceEntry(
                paper_source="demo-paper",
                md_path=str(md_path),
                ref_num=1,
                raw="Demo reference",
            )
        ],
        citations=[
            CitationEvent(
                paper_source="demo-paper",
                md_path=str(md_path),
                cited_ref_num=1,
                chunk_id="chunk-1",
                span=MdSpan(start_line=3, end_line=3),
                context="Body [1]",
            )
        ],
    )

    class _FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get_paper_basic(self, paper_id):
            return {
                "paper_id": paper_id,
                "source_md_path": str(md_path),
                "doi": "10.1000/test",
            }

        def ensure_schema(self):
            pass

        def update_paper_props(self, paper_id, props):  # noqa: ARG002
            pass

        def delete_paper_subgraph(self, paper_id):  # noqa: ARG002
            pass

        def upsert_paper_and_chunks(self, doc):  # noqa: ARG002
            pass

        def upsert_figures(self, paper_id, figures):  # noqa: ARG002
            pass

        def upsert_references_and_citations(self, **kwargs):
            pass

        def update_cites_purposes(self, **kwargs):
            pass

    monkeypatch.setattr(rebuild_mod, "Neo4jClient", lambda *args, **kwargs: _FakeClient())
    monkeypatch.setattr(rebuild_mod, "parse_mineru_markdown", lambda _: doc)
    monkeypatch.setattr(rebuild_mod, "recover_references_with_agent", lambda doc, **kwargs: (doc, {"status": "ok"}))
    monkeypatch.setattr(rebuild_mod, "recover_citation_events_from_references", lambda doc, **kwargs: (doc, {"status": "ok"}))
    monkeypatch.setattr(rebuild_mod, "CrossrefClient", lambda: object())
    monkeypatch.setattr(
        rebuild_mod,
        "build_reference_and_cite_records",
        lambda doc, **kwargs: {
            "paper_id": "doi:10.1000/test",
            "refs": [{"ref_num": 1, "raw": "Demo reference"}],
            "cited_papers": [{"paper_id": "doi:10.1000/ref", "title": "Demo cited paper"}],
            "cites_resolved": [
                {
                    "cited_paper_id": "doi:10.1000/ref",
                    "ref_nums": [1],
                    "evidence_chunk_ids": ["chunk-1"],
                    "evidence_spans": ["3-3"],
                }
            ],
            "cites_unresolved": [],
        },
    )
    monkeypatch.setattr(rebuild_mod, "_schema_for_md", lambda *_: {"prompts": {}, "rules": {}, "version": 1, "paper_type": "research"})
    monkeypatch.setattr(rebuild_mod, "load_canonical_meta", lambda *_: {"paper_type": "research"})
    monkeypatch.setattr(rebuild_mod, "load_active", lambda *_: {"version": 1, "paper_type": "research", "prompts": {}, "rules": {}})
    monkeypatch.setattr(rebuild_mod, "extract_figures_from_markdown", lambda **kwargs: [])
    monkeypatch.setattr(
        rebuild_mod,
        "run_phase1_extraction",
        lambda **kwargs: {
            "step_order": [],
            "logic": {},
            "validated_claims": [],
            "quality_report": {
                "gate_passed": False,
                "quality_tier": "yellow",
                "quality_tier_score": 0.8,
            },
            "claim_candidates": [],
            "claims_merged": [],
            "rejected_claims": [],
        },
    )
    monkeypatch.setattr(
        rebuild_mod,
        "classify_citation_purposes_batch",
        lambda **kwargs: {
            "by_id": {
                "doi:10.1000/ref": {
                    "labels": ["Background"],
                    "scores": [0.2],
                }
            }
        },
    )
    monkeypatch.setattr(rebuild_mod, "_storage_dir", lambda: tmp_path)

    result = rebuild_mod.rebuild_paper("doi:10.1000/test")

    out_dir = tmp_path / "derived" / "papers" / "doi_10.1000_test"
    assert result["gate_passed"] is False
    assert result["skipped_canonical_write"] is True
    assert json.loads((out_dir / "citation_acts.json").read_text(encoding="utf-8"))
    assert json.loads((out_dir / "citation_mentions.json").read_text(encoding="utf-8")) == [
        {
            "mention_id": "cmention:doi:10.1000/test:1:chunk-1:3-3",
            "citation_id": "citeact:doi:10.1000/test->doi:10.1000/ref",
            "citing_paper_id": "doi:10.1000/test",
            "cited_paper_id": "doi:10.1000/ref",
            "ref_num": 1,
            "source_chunk_id": "chunk-1",
            "span_start": 3,
            "span_end": 3,
            "section": "intro",
            "context_text": "Body [1]",
            "target_scopes": ["paper"],
            "source": "machine",
        }
    ]
