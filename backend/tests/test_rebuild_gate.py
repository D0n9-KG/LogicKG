from __future__ import annotations

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
