"""
Test retry logic for update_similarity_for_paper: embedding retries, no lexical fallback.

These tests exercise the incremental similarity-update path.  The environment is
set up with mock cached files so update_similarity_for_paper takes the hot path
(not the rebuild fallthrough) and we can control embedding success/failure via
monkeypatching _embedding_client.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from app.similarity import service as similarity_service


# ---------------------------------------------------------------------------
# Shared environment setup
# ---------------------------------------------------------------------------

def _setup_update_similarity_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    claim_rows: list[dict[str, str]],
    logic_rows: list[dict[str, str]],
) -> None:
    """
    Create minimal on-disk similarity stores so update_similarity_for_paper
    takes the incremental (hot) code path instead of falling through to
    rebuild_similarity_global.
    """
    claim_items_path = tmp_path / "claim_items.jsonl"
    logic_items_path = tmp_path / "logic_items.jsonl"
    claim_meta_path = tmp_path / "claim_meta.json"
    logic_meta_path = tmp_path / "logic_meta.json"
    claim_emb_path = tmp_path / "claim_embeddings.npy"
    logic_emb_path = tmp_path / "logic_embeddings.npy"

    # Empty item stores (no prior embeddings – new items will be embedded fresh).
    claim_items_path.write_text("", encoding="utf-8")
    logic_items_path.write_text("", encoding="utf-8")

    # Meta signals that prior mode was embedding so the hot path is taken.
    claim_meta_path.write_text(json.dumps({"mode": "embedding"}), encoding="utf-8")
    logic_meta_path.write_text(json.dumps({"mode": "embedding"}), encoding="utf-8")

    # Zero-row embedding matrices (dim=3 to give a valid shape).
    np.save(str(claim_emb_path), np.zeros((0, 3), dtype=np.float32))
    np.save(str(logic_emb_path), np.zeros((0, 3), dtype=np.float32))

    item_paths = {"claim": claim_items_path, "logic": logic_items_path}
    meta_paths = {"claim": claim_meta_path, "logic": logic_meta_path}
    emb_paths = {"claim": claim_emb_path, "logic": logic_emb_path}

    class _FakeNeo4jClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list_claim_similarity_rows(self, paper_id: str | None = None):
            return claim_rows

        def list_logic_step_similarity_rows(self, paper_id: str | None = None):
            return logic_rows

        def replace_similar_claim_edges_batch(self, items, model, built_at, mode="embedding"):
            return None

        def replace_similar_logic_edges_batch(self, items, model, built_at):
            return None

    monkeypatch.setattr(similarity_service, "Neo4jClient", _FakeNeo4jClient)
    monkeypatch.setattr(similarity_service, "_items_path", lambda kind: item_paths[kind])
    monkeypatch.setattr(similarity_service, "_meta_path", lambda kind: meta_paths[kind])
    monkeypatch.setattr(similarity_service, "_emb_path", lambda kind: emb_paths[kind])

    # Avoid real faiss dependency for neighbor computation.
    monkeypatch.setattr(similarity_service, "faiss", object())
    monkeypatch.setattr(similarity_service, "_build_index", lambda _x: object())
    monkeypatch.setattr(similarity_service, "_topk_pairs", lambda *args, **kwargs: [])

    # Keep file writes non-destructive (items/embeddings; meta writes are tested separately).
    monkeypatch.setattr(similarity_service, "_write_items", lambda kind, items: None)
    monkeypatch.setattr(similarity_service, "_save_embeddings", lambda kind, x: None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_embedding_retry_success_on_third_attempt(monkeypatch, tmp_path):
    """Embedding succeeds on 3rd attempt; result shows mode=embedding, no degradation."""
    paper_id = "test_paper_001"
    _setup_update_similarity_env(
        monkeypatch,
        tmp_path,
        claim_rows=[{"node_id": "claim_001", "paper_id": paper_id, "text": "Test claim 1"}],
        logic_rows=[],
    )

    sleep_calls: list[float] = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleep_calls.append(seconds))

    call_count = {"count": 0}

    class _FlakyEmbeddingClient:
        def embed_documents(self, texts):
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise RuntimeError("Error code: 502")
            return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(similarity_service, "_embedding_client", lambda: _FlakyEmbeddingClient())

    result = similarity_service.update_similarity_for_paper(paper_id)

    assert result.get("ok") is True
    assert result.get("mode") == "embedding"
    assert "degraded_kinds" not in result
    assert "degradation_events" not in result
    # embed_documents called exactly 3 times (2 failures + 1 success)
    assert call_count["count"] == 3
    # sleep called after each failure (attempts 1 and 2), but not after success
    # 502 is a transient error → exponential backoff: attempt 0 = 5.0s, attempt 1 = 10.0s
    expected_sleeps = [similarity_service._backoff_delay(i) for i in range(2)]
    assert sleep_calls == expected_sleeps


def test_embedding_retry_fails_after_three_attempts(monkeypatch, tmp_path):
    """Embedding that always fails with stable error raises RuntimeError after 3 attempts."""
    paper_id = "test_paper_002"
    _setup_update_similarity_env(
        monkeypatch,
        tmp_path,
        claim_rows=[{"node_id": "claim_002", "paper_id": paper_id, "text": "Test claim 2"}],
        logic_rows=[],
    )

    sleep_calls: list[float] = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleep_calls.append(seconds))

    call_count = {"count": 0}

    class _FailingEmbeddingClient:
        def embed_documents(self, texts):
            call_count["count"] += 1
            # Use 400 (stable error) instead of 502 (transient) for 3-attempt test
            raise RuntimeError("Error code: 400")

    monkeypatch.setattr(similarity_service, "_embedding_client", lambda: _FailingEmbeddingClient())

    with pytest.raises(RuntimeError) as ctx:
        similarity_service.update_similarity_for_paper(paper_id)

    error_msg = str(ctx.value)
    # 400 is stable → _STABLE_MAX=3 attempts
    assert "3 attempts" in error_msg
    assert "embedding unavailable" in error_msg.lower()
    # embed_documents was called exactly 3 times
    assert call_count["count"] == 3
    # stable error: sleep with fixed _STABLE_DELAY=5.0 between retries
    assert sleep_calls == [similarity_service._STABLE_DELAY, similarity_service._STABLE_DELAY]


def test_embedding_never_falls_back_to_lexical(monkeypatch, tmp_path):
    """Successful embedding produces mode=embedding; no lexical fallback in results."""
    paper_id = "test_paper_003"
    _setup_update_similarity_env(
        monkeypatch,
        tmp_path,
        claim_rows=[{"node_id": "claim_003", "paper_id": paper_id, "text": "Test claim 3"}],
        logic_rows=[],
    )

    # Guard: rebuild should NOT be called since the hot path is set up correctly.
    def _unexpected_rebuild(*args, **kwargs):
        raise AssertionError("rebuild_similarity_global should not be called - hot path failed")

    class _StableEmbeddingClient:
        def embed_documents(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

    monkeypatch.setattr(similarity_service, "rebuild_similarity_global", _unexpected_rebuild)
    monkeypatch.setattr(similarity_service, "_embedding_client", lambda: _StableEmbeddingClient())
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    result = similarity_service.update_similarity_for_paper(paper_id)

    assert result.get("ok") is True
    assert result.get("mode") == "embedding"
    assert result.get("mode") != "lexical"
    assert result.get("mode") != "mixed"
    assert "degraded_kinds" not in result
    assert "degradation_events" not in result
