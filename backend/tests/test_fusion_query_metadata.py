from types import SimpleNamespace

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
