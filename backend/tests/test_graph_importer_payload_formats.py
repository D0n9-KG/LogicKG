from __future__ import annotations

import json
from pathlib import Path

from app.ingest.graph_importer import import_youtu_graph


class _DummyNeo4jClient:
    def __init__(self) -> None:
        self.entities: list[dict] = []
        self.relations: list[dict] = []
        self.chapter_links: tuple[str, list[str]] | None = None

    def create_knowledge_entities(self, entities: list[dict]) -> int:
        self.entities = list(entities)
        return len(entities)

    def create_entity_relations(self, relations: list[dict]) -> int:
        self.relations = list(relations)
        return len(relations)

    def link_chapter_entities(self, chapter_id: str, entity_ids: list[str]) -> None:
        self.chapter_links = (chapter_id, list(entity_ids))


def test_import_youtu_graph_supports_triple_list_payload(tmp_path: Path) -> None:
    graph_path = tmp_path / "graph_list_payload.json"
    payload = [
        {
            "start_node": {
                "label": "entity",
                "properties": {"name": "Young's modulus", "schema_type": "concept", "chunk id": "A1"},
            },
            "relation": "has_attribute",
            "end_node": {
                "label": "attribute",
                "properties": {"name": "symbol: E", "chunk id": "A1"},
            },
        },
        {
            "start_node": {
                "label": "entity",
                "properties": {"name": "Young's modulus", "schema_type": "concept", "chunk id": "A1"},
            },
            "relation": "is_a",
            "end_node": {
                "label": "entity",
                "properties": {"name": "elastic parameter", "chunk id": "A1"},
            },
        },
    ]
    graph_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    dummy = _DummyNeo4jClient()
    result = import_youtu_graph(
        graph_json_path=str(graph_path),
        textbook_id="tb:test",
        chapter_id="tb:test:ch000",
        neo4j_client=dummy,  # type: ignore[arg-type]
    )

    assert result["entity_count"] == 3
    assert result["relation_count"] == 2
    assert result["community_count"] == 0
    assert len(dummy.entities) == 3
    assert len(dummy.relations) == 2
    assert dummy.chapter_links is not None
    assert dummy.chapter_links[0] == "tb:test:ch000"
