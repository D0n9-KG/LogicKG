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


def test_list_proposition_similarity_rows_returns_claim_and_textbook_provenance() -> None:
    class _PropSession(_FakeSession):
        def run(self, query: str, **params):
            self.last_query = str(query)
            self.last_params = dict(params)
            return [
                {
                    "node_id": "pr-1",
                    "paper_id": "doi:10.1000/example",
                    "paper_source": "paper-A",
                    "text": "Finite element discretization stabilizes PDE solving.",
                    "source_kind": "claim",
                    "source_id": "cl-1",
                    "chapter_id": None,
                    "textbook_id": None,
                },
                {
                    "node_id": "pr-2",
                    "paper_id": "",
                    "paper_source": "",
                    "text": "The finite element basis interpolates the field variable.",
                    "source_kind": "textbook_entity",
                    "source_id": "ent-7",
                    "chapter_id": "tb:1:ch001",
                    "textbook_id": "tb:1",
                },
            ]

    fake_session = _PropSession()
    client = object.__new__(Neo4jClient)
    client._driver = _FakeDriver(fake_session)

    rows = client.list_proposition_similarity_rows(limit=5)

    assert rows[0]["source_kind"] == "claim"
    assert rows[0]["source_id"] == "cl-1"
    assert rows[1]["source_kind"] == "textbook_entity"
    assert rows[1]["chapter_id"] == "tb:1:ch001"
    assert rows[1]["textbook_id"] == "tb:1"
    assert fake_session.last_params["limit"] == 5


def test_get_grounding_rows_for_structured_ids_preserves_quotes_and_locations() -> None:
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
            if "UNWIND $proposition_ids AS prop_id" in self.last_query:
                return [
                    {
                        "source_kind": "proposition",
                        "source_id": "pr-2",
                        "quote": "The element basis interpolates the field variable.",
                        "chunk_id": None,
                        "md_path": None,
                        "start_line": None,
                        "end_line": None,
                        "textbook_id": "tb:1",
                        "chapter_id": "tb:1:ch001",
                        "evidence_event_id": "ev-2",
                        "evidence_event_type": "SUPPORTS",
                    }
                ]
            return []

    fake_session = _GroundingSession()
    client = object.__new__(Neo4jClient)
    client._driver = _FakeDriver(fake_session)

    rows = client.get_grounding_rows_for_structured_ids(
        [
            {"kind": "claim", "id": "cl-1"},
            {"kind": "proposition", "id": "pr-2"},
        ],
        limit=10,
    )

    assert rows[0]["quote"] == "Finite element method discretizes the domain."
    assert rows[0]["chunk_id"] == "c1"
    assert rows[0]["start_line"] == 11
    assert rows[0]["evidence_event_id"] == "ev-1"
    assert rows[1]["textbook_id"] == "tb:1"
    assert rows[1]["chapter_id"] == "tb:1:ch001"
    assert rows[1]["evidence_event_type"] == "SUPPORTS"


def test_list_proposition_structured_rows_preserves_evidence_event_provenance() -> None:
    class _PropStructuredSession(_FakeSession):
        def run(self, query: str, **params):
            self.last_query = str(query)
            self.last_params = dict(params)
            return [
                {
                    "kind": "proposition",
                    "source_id": "pr-1",
                    "proposition_id": "pr-1",
                    "paper_id": "doi:10.1000/example",
                    "paper_source": "paper-A",
                    "text": "Finite element discretization stabilizes PDE solving.",
                    "source_kind": "claim",
                    "source_ref_id": "cl-1",
                    "textbook_id": None,
                    "chapter_id": None,
                    "evidence_quote": "Finite element method discretizes the domain.",
                    "evidence_event_id": "ev-1",
                    "evidence_event_type": "SUPPORTS",
                },
                {
                    "kind": "proposition",
                    "source_id": "pr-2",
                    "proposition_id": "pr-2",
                    "paper_id": "",
                    "paper_source": "",
                    "text": "The finite element basis interpolates the field variable.",
                    "source_kind": "textbook_entity",
                    "source_ref_id": "ent-7",
                    "textbook_id": "tb:1",
                    "chapter_id": "tb:1:ch001",
                    "evidence_quote": "The element basis interpolates the field variable.",
                    "evidence_event_id": "ev-2",
                    "evidence_event_type": "SUPPORTS",
                },
            ]

    fake_session = _PropStructuredSession()
    client = object.__new__(Neo4jClient)
    client._driver = _FakeDriver(fake_session)

    rows = client.list_proposition_structured_rows(limit=5)

    assert rows[0]["evidence_event_id"] == "ev-1"
    assert rows[0]["evidence_event_type"] == "SUPPORTS"
    assert rows[1]["evidence_event_id"] == "ev-2"
    assert rows[1]["chapter_id"] == "tb:1:ch001"
