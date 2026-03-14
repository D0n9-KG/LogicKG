from app.graph.neo4j_client import _author_id_for_name


def test_author_id_for_name_is_stable_and_normalized() -> None:
    left = _author_id_for_name(" Alice   Smith ")
    right = _author_id_for_name("alice smith")

    assert left == right
    assert left.startswith("author:")
    assert len(left) > len("author:")


def test_author_id_for_name_returns_empty_for_blank_input() -> None:
    assert _author_id_for_name("") == ""
    assert _author_id_for_name("   ") == ""
