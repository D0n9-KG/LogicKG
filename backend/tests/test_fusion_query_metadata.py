from app.graph.neo4j_client import Neo4jClient


class _FakeSession:
    def __init__(self) -> None:
        self.last_query = ""
        self.last_params = {}

    def run(self, query: str, **params):
        self.last_query = str(query)
        self.last_params = dict(params)
        has_joined_metadata = "tb.title AS textbook_title" in self.last_query and "tc.title AS chapter_title" in self.last_query
        row = {
            "paper_source": "paper-A",
            "paper_id": "doi:10.1000/example",
            "logic_step_id": "ls-1",
            "step_type": "Method",
            "entity_id": "ent-1",
            "entity_name": "Finite Element Method",
            "entity_type": "method",
            "description": "Numerical discretization method",
            "score": 0.84,
            "source_chapter_id": "tb:1:ch001",
        }
        if has_joined_metadata:
            row["textbook_id"] = "tb:1"
            row["textbook_title"] = "Continuum Mechanics"
            row["chapter_id"] = "tb:1:ch001"
            row["chapter_title"] = "Finite Element Foundations"
        return [row]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeDriver:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def session(self):
        return self._session

    def close(self):
        return None


def test_list_fusion_basics_by_paper_sources_includes_textbook_and_chapter_metadata() -> None:
    fake_session = _FakeSession()
    client = object.__new__(Neo4jClient)
    client._driver = _FakeDriver(fake_session)

    rows = client.list_fusion_basics_by_paper_sources(["paper-A"], limit=5)

    assert rows[0]["textbook_title"] == "Continuum Mechanics"
    assert rows[0]["chapter_title"] == "Finite Element Foundations"
    assert fake_session.last_params["paper_sources"] == ["paper-A"]


def test_get_grounding_rows_for_structured_ids_preserves_quotes_and_locations_for_active_kinds() -> None:
    class _GroundingSession(_FakeSession):
        def run(self, query: str, **params):
            self.last_query = str(query)
            self.last_params = dict(params)
            if "UNWIND $claim_ids AS claim_id" in self.last_query:
                return [
                    {
                        "source_kind": "claim",
                        "source_id": "cl-1",
                        "quote": "Finite element method discretizes the domain.",
                        "chunk_id": "c1",
                        "md_path": "runs/paper-A/content.md",
                        "start_line": 11,
                        "end_line": 12,
                        "textbook_id": None,
                        "chapter_id": None,
                        "evidence_event_id": "ev-1",
                        "evidence_event_type": "SUPPORTS",
                    }
                ]
            if "UNWIND $logic_ids AS logic_step_id" in self.last_query:
                return [
                    {
                        "source_kind": "logic_step",
                        "source_id": "ls-2",
                        "quote": "Method step summary.",
                        "chunk_id": "c2",
                        "md_path": "runs/paper-A/content.md",
                        "start_line": 20,
                        "end_line": 21,
                        "textbook_id": None,
                        "chapter_id": None,
                        "evidence_event_id": None,
                        "evidence_event_type": None,
                    }
                ]
            return []

    fake_session = _GroundingSession()
    client = object.__new__(Neo4jClient)
    client._driver = _FakeDriver(fake_session)

    rows = client.get_grounding_rows_for_structured_ids(
        [
            {"kind": "claim", "id": "cl-1"},
            {"kind": "logic_step", "id": "ls-2"},
            {"kind": "proposition", "id": "pr-legacy"},
        ],
        limit=10,
    )

    assert rows[0]["quote"] == "Finite element method discretizes the domain."
    assert rows[0]["chunk_id"] == "c1"
    assert rows[0]["start_line"] == 11
    assert rows[0]["evidence_event_id"] == "ev-1"
    assert rows[1]["source_kind"] == "logic_step"
    assert rows[1]["source_id"] == "ls-2"
    assert "proposition_ids" not in fake_session.last_params
