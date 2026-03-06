# backend/tests/test_neo4j_logic_claims_empty_steps_guard.py
"""
Tests that claims are written even when logic steps list is empty.

Root cause: Old Cypher chained `WITH p / UNWIND $steps AS s / ... / WITH p / UNWIND $claims AS c`,
so empty $steps collapses the entire pipeline and claims are silently dropped.

Fix: Independent CALL blocks for logic step writes + claims at outer scope after all CALL blocks.
"""
from __future__ import annotations

import inspect
import re

from app.graph.neo4j_client import Neo4jClient


def _extract_upsert_logic_cypher() -> str:
    """Extract the Cypher string from upsert_logic_steps_and_claims."""
    src = inspect.getsource(Neo4jClient.upsert_logic_steps_and_claims)
    match = re.search(r'cypher\s*=\s*"""(.*?)"""', src, re.DOTALL)
    assert match, "Could not find cypher string in upsert_logic_steps_and_claims"
    return match.group(1)


def test_logic_step_writes_are_isolated_from_claim_writes() -> None:
    """Logic step writes must be in independent CALL blocks that return counts."""
    cypher = _extract_upsert_logic_cypher()

    # All logic step operations are in CALL blocks with RETURN counts
    assert "CALL {" in cypher
    assert "RETURN count(*) AS logic_steps_written" in cypher
    assert "RETURN count(*) AS next_edges_written" in cypher
    assert "RETURN count(*) AS logic_step_evidence_written" in cypher

    # Claim writes occur after isolated step subqueries
    claims_pos = cypher.index("UNWIND $claims AS c")
    steps_end_pos = cypher.index("RETURN count(*) AS logic_step_evidence_written")
    assert claims_pos > steps_end_pos, "claim writes must occur after isolated step subqueries"


def test_claim_write_path_survives_empty_steps() -> None:
    """Claims are written even when $steps is empty (defensive OPTIONAL MATCH + FOREACH)."""
    cypher = _extract_upsert_logic_cypher()

    # Claims UNWIND is at outer scope (not inside CALL block dependent on $steps)
    assert "UNWIND $claims AS c" in cypher

    # Claim-to-step linking uses OPTIONAL MATCH + FOREACH (creates edge only if step exists)
    assert "OPTIONAL MATCH (ls:LogicStep {logic_step_id: paper_id + ':' + c.step_type})" in cypher
    assert "FOREACH (_ IN CASE WHEN ls IS NULL THEN [] ELSE [1] END |" in cypher

    # Evidence and targets writes are in independent CALL blocks (no cross-contamination)
    assert "RETURN count(*) AS claim_evidence_written" in cypher
    assert "RETURN count(*) AS claim_targets_written" in cypher


def test_no_direct_steps_unwind_pipeline_before_claims() -> None:
    """Must NOT use the old chained 'WITH p / UNWIND $steps' pattern at outer scope."""
    cypher = _extract_upsert_logic_cypher()

    # The old pattern that causes the bug: 'WITH p' followed by 'UNWIND $steps' at outer scope
    # (This would cause empty $steps to collapse the entire pipeline including claims)
    chained_pattern = re.compile(r"WITH\s+p\s*\n\s*UNWIND\s+\$steps\s+AS\s+s", re.DOTALL)
    assert not chained_pattern.search(cypher), (
        "direct UNWIND $steps pipeline at outer scope can collapse rows and skip claim writes when steps are empty"
    )
