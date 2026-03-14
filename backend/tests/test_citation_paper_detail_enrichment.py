from __future__ import annotations

from app.graph.neo4j_client import _load_citation_enrichment_artifacts, _merge_outgoing_citation_enrichment


def test_load_citation_enrichment_artifacts_reads_both_payloads(tmp_path, monkeypatch) -> None:
    paper_dir = tmp_path / "derived" / "papers" / "doi_10.1000_example"
    paper_dir.mkdir(parents=True)
    (paper_dir / "citation_acts.json").write_text(
        '[{"citation_id":"citeact:paper->doi:10.1000/cite","cited_paper_id":"doi:10.1000/cite"}]',
        encoding="utf-8",
    )
    (paper_dir / "citation_mentions.json").write_text(
        '[{"mention_id":"m1","cited_paper_id":"doi:10.1000/cite","ref_num":2}]',
        encoding="utf-8",
    )

    monkeypatch.setattr("app.graph.neo4j_client.settings.storage_dir", str(tmp_path))

    acts, mentions = _load_citation_enrichment_artifacts("doi:10.1000/example")

    assert acts == [{"citation_id": "citeact:paper->doi:10.1000/cite", "cited_paper_id": "doi:10.1000/cite"}]
    assert mentions == [{"mention_id": "m1", "cited_paper_id": "doi:10.1000/cite", "ref_num": 2}]


def test_merge_outgoing_citation_enrichment_applies_semantic_overlay_and_mentions() -> None:
    outgoing_raw = [
        {
            "cited_paper_id": "doi:10.1000/cite",
            "cited_doi": "10.1000/cite",
            "cited_title": "Target Paper",
            "total_mentions": 3,
            "ref_nums": [3, 2],
            "purpose_labels": ["MethodUse"],
            "purpose_scores": [0.81],
        }
    ]
    human_cites = {
        "doi:10.1000/cite": {
            "labels": ["CritiqueLimit", "FutureDirection"],
            "scores": [0.88, 0.64],
        }
    }
    citation_acts = [
        {
            "citation_id": "citeact:paper->doi:10.1000/cite",
            "cited_paper_id": "doi:10.1000/cite",
            "evidence_chunk_ids": ["chunk-9", "chunk-3"],
            "evidence_spans": ["88-90", "54-55"],
        }
    ]
    citation_mentions = [
        {
            "mention_id": "m2",
            "cited_paper_id": "doi:10.1000/cite",
            "ref_num": 3,
            "source_chunk_id": "chunk-9",
            "span_start": 88,
            "span_end": 90,
            "section": "discussion",
            "context_text": "future work reference",
        },
        {
            "mention_id": "m1",
            "cited_paper_id": "doi:10.1000/cite",
            "ref_num": 2,
            "source_chunk_id": "chunk-3",
            "span_start": 54,
            "span_end": 55,
            "section": "results",
            "context_text": "limitation discussion",
        },
    ]

    outgoing = _merge_outgoing_citation_enrichment(
        outgoing_raw=outgoing_raw,
        human_cites=human_cites,
        cites_cleared=set(),
        needs_review=True,
        citation_acts=citation_acts,
        citation_mentions=citation_mentions,
    )

    assert len(outgoing) == 1
    cite = outgoing[0]
    assert cite["purpose_source"] == "human"
    assert cite["purpose_labels"] == ["CritiqueLimit", "FutureDirection"]
    assert cite["pending_machine_purpose_labels"] == ["MethodUse"]
    assert cite["semantic"]["polarity"] == "negative"
    assert cite["semantic"]["semantic_signals"] == ["gap_hint", "future_opportunity_hint"]
    assert cite["semantic"]["target_scopes"] == ["paper", "claim", "gap"]
    assert cite["semantic"]["evidence_chunk_ids"] == ["chunk-9", "chunk-3"]
    assert cite["semantic"]["evidence_spans"] == ["88-90", "54-55"]
    assert [item["mention_id"] for item in cite["mentions"]] == ["m1", "m2"]
    assert cite["mentions"][0]["section"] == "results"
    assert cite["mentions"][0]["context_text"] == "limitation discussion"
