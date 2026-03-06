# backend/tests/test_p0_empty_logic_steps_layers.py
from __future__ import annotations

from typing import Any

from app.extraction.orchestrator import _default_logic_extractor, run_phase1_extraction
from app.graph.neo4j_client import Neo4jClient
from app.ingest.models import Chunk, DocumentIR, MdSpan, PaperDraft
from app.llm.logic_claims_v2 import extract_logic_and_claims_v2


def _doc() -> DocumentIR:
    return DocumentIR(
        paper=PaperDraft(
            paper_source="paperA",
            md_path="C:/tmp/paperA/source.md",
            title="Paper A",
            title_alt=None,
            authors=["Alice"],
            doi="10.1000/papera",
            year=2024,
        ),
        chunks=[
            Chunk(
                chunk_id="c1",
                paper_source="paperA",
                md_path="C:/tmp/paperA/source.md",
                span=MdSpan(start_line=1, end_line=3),
                section="Background",
                kind="block",
                text="Background text",
            ),
            Chunk(
                chunk_id="c2",
                paper_source="paperA",
                md_path="C:/tmp/paperA/source.md",
                span=MdSpan(start_line=4, end_line=8),
                section="Method",
                kind="block",
                text="Method text",
            ),
        ],
        references=[],
        citations=[],
    )


def _schema() -> dict[str, Any]:
    return {
        "paper_type": "research",
        "version": 1,
        "steps": [
            {"id": "Background", "enabled": True, "order": 0},
            {"id": "Method", "enabled": True, "order": 1},
        ],
        "claim_kinds": [
            {"id": "Definition", "enabled": True},
            {"id": "Comparison", "enabled": True},
        ],
        "rules": {
            "phase1_gate_supported_ratio_min": 0.0,
            "phase1_gate_step_coverage_min": 0.0,
            "phase2_gate_critical_slot_coverage_min": 0.0,
            "phase2_gate_conflict_rate_max": 1.0,
        },
    }


class _CaptureSession:
    def __init__(self, sink: list[tuple[str, dict[str, Any]]]):
        self.sink = sink

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, cypher: str, **params):
        self.sink.append((cypher, params))
        return []


class _CaptureDriver:
    def __init__(self, sink: list[tuple[str, dict[str, Any]]]):
        self.sink = sink

    def session(self):
        return _CaptureSession(self.sink)


def test_layer1_extract_logic_filters_empty_summary(monkeypatch):
    def _fake_call_json(system: str, user: str) -> dict[str, Any]:
        return {
            "logic": {
                "Background": {"summary": "   ", "confidence": 0.9},
                "Method": {"summary": "Method summary", "confidence": 0.8},
            },
            "claims": [],
        }

    monkeypatch.setattr("app.llm.logic_claims_v2.call_validated_json", lambda *a, **kw: (_ for _ in ()).throw(Exception("skip")))
    monkeypatch.setattr("app.llm.logic_claims_v2.call_json", _fake_call_json)

    out = extract_logic_and_claims_v2(
        doc=_doc(),
        paper_id="doi:10.1000/papera",
        schema=_schema(),
    )
    assert "Background" not in out["logic"]
    assert out["logic"]["Method"]["summary"] == "Method summary"


def test_layer2_default_logic_extractor_final_sanitize(monkeypatch):
    def _fake_extract(*, doc, paper_id, schema, **kwargs):
        return {
            "logic": {
                "Background": {"summary": "", "evidence_chunk_ids": []},
                "Method": {"summary": "Method summary", "evidence_chunk_ids": ["c2"]},
            },
            "claims": [],
        }

    monkeypatch.setattr("app.llm.logic_claims_v2.extract_logic_and_claims_v2", _fake_extract)

    out = _default_logic_extractor(
        doc=_doc(),
        paper_id="doi:10.1000/papera",
        schema=_schema(),
    )
    assert list(out["logic"].keys()) == ["Method"]


def test_layer3_neo4j_defensive_filter_skips_empty_logic_step():
    captured: list[tuple[str, dict[str, Any]]] = []
    client = Neo4jClient.__new__(Neo4jClient)
    client._driver = _CaptureDriver(captured)

    logic = {
        "Background": {"summary": "   ", "evidence_chunk_ids": []},
        "Method": {"summary": "Method summary", "evidence_chunk_ids": []},
    }

    client.upsert_logic_steps_and_claims(
        paper_id="doi:10.1000/papera",
        logic=logic,
        claims=[],
        step_order=["Background", "Method"],
    )

    assert len(captured) == 1
    _, params = captured[0]
    steps = params["steps"]
    assert len(steps) == 1
    assert steps[0]["step_type"] == "Method"


def test_layer4_orchestrator_quality_gate_marks_empty_logic_steps(tmp_path):
    def _logic_extractor(*, doc, paper_id, schema):
        return {
            "logic": {
                "Background": {"summary": " ", "evidence_chunk_ids": []},  # empty
                "Method": {"summary": "Method summary", "evidence_chunk_ids": ["c2"]},
            },
            "step_order": ["Background", "Method"],
        }

    def _claim_extractor(*, doc, paper_id, schema, step_order):
        return [
            {
                "text": "Method improves accuracy.",
                "confidence": 0.9,
                "step_type": "Method",
                "kinds": ["Comparison"],
                "origin_chunk_id": "c2",
                "worker_id": "w1",
            }
        ]

    out = run_phase1_extraction(
        doc=_doc(),
        paper_id="doi:10.1000/papera",
        cite_rec={"cites_resolved": []},
        schema=_schema(),
        artifacts_dir=tmp_path / "phase1",
        logic_extractor=_logic_extractor,
        claim_extractor=_claim_extractor,
        allow_weak=False,
    )
    report = out["quality_report"]
    assert int(report.get("logic_steps_empty_count") or 0) == 1
    assert report["gate_passed"] is False
    assert "empty_logic_steps" in list(report.get("gate_fail_reasons") or [])
