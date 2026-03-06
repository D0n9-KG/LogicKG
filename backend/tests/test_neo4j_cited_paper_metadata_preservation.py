# backend/tests/test_neo4j_cited_paper_metadata_preservation.py
"""
Tests that cited Paper metadata is NOT overwritten by citation-resolution payloads.

Root cause: `MERGE (q:Paper {paper_id:...}) SET q += cp` unconditionally overwrites
all properties, clobbering title/year/authors of already-ingested papers.

Fix: ON CREATE SET q += cp / ON MATCH SET with COALESCE for protective properties
and DOI-enrichment logic for the doi field.
"""
from __future__ import annotations

import re


def _extract_upsert_cypher() -> str:
    """Extract the Cypher string from upsert_references_and_citations."""
    from app.graph.neo4j_client import Neo4jClient
    import inspect

    src = inspect.getsource(Neo4jClient.upsert_references_and_citations)
    # Find the triple-quoted cypher string
    match = re.search(r'cypher\s*=\s*"""(.*?)"""', src, re.DOTALL)
    assert match, "Could not find cypher string in upsert_references_and_citations"
    return match.group(1)


def _extract_resolve_cypher() -> str:
    """Extract the Cypher string from resolve_reference."""
    from app.graph.neo4j_client import Neo4jClient
    import inspect

    src = inspect.getsource(Neo4jClient.resolve_reference)
    match = re.search(r'cypher\s*=\s*"""(.*?)"""', src, re.DOTALL)
    assert match, "Could not find cypher string in resolve_reference"
    return match.group(1)


# ---------------------------------------------------------------------------
# Tests for upsert_references_and_citations Cypher
# ---------------------------------------------------------------------------

class TestUpsertCitedPaperMetadataPreservation:
    """Verify the Cypher in upsert_references_and_citations uses safe ON CREATE/ON MATCH pattern."""

    def test_uses_on_create_set_not_bare_set(self):
        """ON CREATE SET protects existing nodes from full overwrite."""
        cypher = _extract_upsert_cypher()
        # Must NOT have a bare (non-ON-CREATE) 'SET q += cp' immediately after MERGE
        # Use regex: look for MERGE on cited paper then a bare SET q += cp
        bare_set_pattern = re.compile(
            r"MERGE\s*\(q:Paper\s*\{paper_id:\s*cp\.paper_id\}\)\s*\n\s*SET\s+q\s*\+=\s*cp",
            re.DOTALL,
        )
        assert not bare_set_pattern.search(cypher), (
            "Bare 'SET q += cp' (without ON CREATE) overwrites existing Paper properties unconditionally"
        )
        assert "ON CREATE SET q += cp" in cypher, (
            "ON CREATE SET q += cp must be used so new nodes get all properties"
        )

    def test_uses_on_match_set_with_coalesce(self):
        """ON MATCH SET uses COALESCE to protect existing title/authors/year."""
        cypher = _extract_upsert_cypher()
        assert "ON MATCH SET" in cypher
        # Protective fields must use coalesce
        assert "coalesce(q.title, cp.title)" in cypher, "title must be protected with coalesce"
        assert "coalesce(q.authors, cp.authors)" in cypher, "authors must be protected with coalesce"
        assert "coalesce(q.year, cp.year)" in cypher, "year must be protected with coalesce"

    def test_doi_is_updated_when_incoming_is_non_null(self):
        """DOI from crossref should update the existing DOI (authoritative enrichment)."""
        cypher = _extract_upsert_cypher()
        # DOI should use a CASE expression (update only if incoming DOI is non-null/non-empty)
        assert "cp.doi" in cypher, "DOI from citation payload must be referenced"
        assert "CASE" in cypher, "DOI update must use CASE to avoid nulling existing DOI"

    def test_doi_not_blanked_when_incoming_is_null(self):
        """When incoming DOI is null or empty, existing DOI must be preserved."""
        cypher = _extract_upsert_cypher()
        # The CASE logic must check for NULL and empty string
        assert "cp.doi IS NULL" in cypher, "Must guard against NULL incoming DOI"

    def test_paper_id_always_set(self):
        """paper_id (the MERGE key) must always be set."""
        cypher = _extract_upsert_cypher()
        assert "q.paper_id = cp.paper_id" in cypher, "paper_id must always be set on MATCH"

    def test_md_path_uses_coalesce(self):
        """md_path belongs to the original paper's ingest, not citation data."""
        cypher = _extract_upsert_cypher()
        assert "coalesce(q.md_path, cp.md_path)" in cypher, "md_path must be protected with coalesce"

    def test_independent_call_blocks_prevent_empty_list_short_circuit(self):
        """
        Each UNWIND stage must be in an independent CALL { WITH p ... } block.

        Root cause: chained UNWIND via 'WITH p / UNWIND' at outer scope means an
        empty first list (e.g. $refs=[]) collapses all downstream stages.  Independent
        CALL blocks guarantee each stage runs regardless of the others.
        """
        cypher = _extract_upsert_cypher()

        # Each list must have its own CALL block
        assert "UNWIND $refs" in cypher
        assert "UNWIND $cited_papers" in cypher
        assert "UNWIND $cites_resolved" in cypher
        assert "UNWIND $cites_unresolved" in cypher

        # Must use at least 4 CALL blocks (one per UNWIND stage)
        assert cypher.count("CALL {") >= 4, "Each of the four UNWIND stages must be inside its own CALL block"

        # Verify structural integrity: every UNWIND $<list> must appear inside a CALL block.
        # We detect this by checking that no UNWIND appears OUTSIDE a CALL (i.e., at the outer query level).
        # A UNWIND at outer level would be preceded by a '}' closing a prior CALL block then a newline,
        # or immediately after 'WITH p' without an enclosing 'CALL {'.
        # Simple proxy: count CALL blocks vs UNWIND $param occurrences - they must be equal.
        call_block_count = cypher.count("CALL {")
        unwind_param_count = sum(
            1 for kw in ("$refs", "$cited_papers", "$cites_resolved", "$cites_unresolved")
            if f"UNWIND {kw}" in cypher
        )
        assert call_block_count >= unwind_param_count, (
            f"Expected at least {unwind_param_count} CALL blocks for {unwind_param_count} UNWIND stages, "
            f"got {call_block_count}"
        )


# ---------------------------------------------------------------------------
# Tests for resolve_reference Cypher
# ---------------------------------------------------------------------------

class TestResolveCitedPaperMetadataPreservation:
    """Verify the Cypher in resolve_reference uses safe ON CREATE/ON MATCH pattern."""

    def test_uses_on_create_set_not_bare_set(self):
        """ON CREATE SET protects existing nodes from full overwrite."""
        cypher = _extract_resolve_cypher()
        bare_set_pattern = re.compile(
            r"MERGE\s*\(q:Paper\s*\{paper_id:\s*\$cited_paper\.paper_id\}\)\s*\n\s*SET\s+q\s*\+=\s*\$cited_paper",
            re.DOTALL,
        )
        assert not bare_set_pattern.search(cypher), (
            "Bare 'SET q += $cited_paper' (without ON CREATE) overwrites existing Paper properties unconditionally"
        )
        assert "ON CREATE SET q += $cited_paper" in cypher, (
            "ON CREATE SET must be used so new nodes get all properties"
        )

    def test_uses_on_match_set_with_coalesce(self):
        """ON MATCH SET uses COALESCE to protect existing title/authors/year."""
        cypher = _extract_resolve_cypher()
        assert "ON MATCH SET" in cypher
        assert "coalesce(q.title, $cited_paper.title)" in cypher, "title must be protected with coalesce"
        assert "coalesce(q.authors, $cited_paper.authors)" in cypher, "authors must be protected with coalesce"
        assert "coalesce(q.year, $cited_paper.year)" in cypher, "year must be protected with coalesce"

    def test_doi_is_updated_when_incoming_is_non_null(self):
        """DOI from resolution is authoritative: must be applied when present."""
        cypher = _extract_resolve_cypher()
        assert "$cited_paper.doi" in cypher
        assert "CASE" in cypher

    def test_doi_not_blanked_when_incoming_is_null(self):
        """When incoming DOI is null or empty, existing DOI must be preserved."""
        cypher = _extract_resolve_cypher()
        assert "$cited_paper.doi IS NULL" in cypher, "Must guard against NULL incoming DOI"

    def test_paper_id_always_set(self):
        """paper_id (the MERGE key) must always be set."""
        cypher = _extract_resolve_cypher()
        assert "q.paper_id = $cited_paper.paper_id" in cypher

    def test_merge_cites_edge_still_present(self):
        """MERGE for the CITES relationship must still come after the Paper MERGE."""
        cypher = _extract_resolve_cypher()
        # After the new ON MATCH block, the CITES edge must still be created
        paper_merge_pos = cypher.index("MERGE (q:Paper")
        cites_merge_pos = cypher.index("MERGE (p)-[c:CITES]")
        assert cites_merge_pos > paper_merge_pos, (
            "CITES edge MERGE must come after cited Paper MERGE"
        )

    def test_delete_unresolved_still_present(self):
        """DELETE of the CITES_UNRESOLVED relationship must still be in the Cypher."""
        cypher = _extract_resolve_cypher()
        assert "DELETE u" in cypher, "CITES_UNRESOLVED relationship must be deleted on resolution"
