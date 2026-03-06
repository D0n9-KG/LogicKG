"""Tests for proposition clustering."""
from app.similarity.clustering import cluster_propositions


def test_clustering_basic():
    """Test basic clustering with synthetic data."""
    # Two distinct clusters
    embeddings = [
        [1.0, 0.0, 0.0],  # Cluster A
        [0.9, 0.1, 0.0],  # Cluster A
        [0.0, 1.0, 0.0],  # Cluster B
        [0.0, 0.9, 0.1],  # Cluster B
    ]
    texts = ["Text A1", "Text A2", "Text B1", "Text B2"]

    groups = cluster_propositions(embeddings, texts, threshold=0.8)

    assert len(groups) == 2, "Should find 2 distinct clusters"
    assert all(g["member_count"] == 2 for g in groups), "Each cluster should have 2 members"


def test_clustering_empty():
    """Test clustering with empty input."""
    groups = cluster_propositions([], [])
    assert groups == []


def test_clustering_single():
    """Test clustering with single item."""
    embeddings = [[1.0, 0.0, 0.0]]
    texts = ["Single text"]

    groups = cluster_propositions(embeddings, texts, threshold=0.85)

    assert len(groups) == 1
    assert groups[0]["member_count"] == 1
    assert groups[0]["representative_text"] == "Single text"


def test_clustering_louvain_basic():
    """Louvain mode should separate two obvious semantic groups."""
    embeddings = [
        [1.0, 0.0, 0.0],
        [0.95, 0.05, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.95, 0.05],
    ]
    texts = ["A1", "A2", "B1", "B2"]

    groups = cluster_propositions(embeddings, texts, threshold=0.82, method="louvain")

    assert len(groups) == 2
    assert sorted(g["member_count"] for g in groups) == [2, 2]


def test_clustering_hybrid_basic():
    """Hybrid mode should keep coarse communities while refining within them."""
    embeddings = [
        [1.0, 0.0, 0.0],
        [0.96, 0.04, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.96, 0.04],
    ]
    texts = ["A1", "A2", "B1", "B2"]

    groups = cluster_propositions(embeddings, texts, threshold=0.82, method="hybrid")

    assert len(groups) == 2
    assert sorted(g["member_count"] for g in groups) == [2, 2]
