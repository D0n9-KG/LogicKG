from __future__ import annotations

import pytest

from app.similarity import service as similarity_service


@pytest.mark.parametrize(
    ("status_code", "error_label", "attempts_attr"),
    [
        (502, "transient", "_TRANSIENT_MAX"),
        (400, "stable", "_STABLE_MAX"),
    ],
)
def test_embedding_retry_policy_is_explicit(
    monkeypatch,
    tmp_path,
    status_code: int,
    error_label: str,
    attempts_attr: str,
):
    """
    rebuild_similarity_global should follow the shared retry policy for transient/stable errors.
    """
    class _FakeNeo4jClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def list_claim_similarity_rows(self, paper_id: str | None = None):
            return [
                {"node_id": "c1", "paper_id": "p1", "text": "Granular flow increases with vibration."},
                {"node_id": "c2", "paper_id": "p2", "text": "Vibration increases granular flow rate."},
            ]

        def list_logic_step_similarity_rows(self, paper_id: str | None = None):
            return []

    class _FailingEmbeddingClient:
        def embed_documents(self, texts):  # noqa: ANN001
            raise RuntimeError(f"Embedding API error {status_code}: injected failure")

    # Track sleep calls so the test never actually sleeps.
    sleep_calls: list[float] = []
    monkeypatch.setattr("time.sleep", lambda seconds: sleep_calls.append(seconds))

    monkeypatch.setattr(similarity_service, "Neo4jClient", _FakeNeo4jClient)
    # Ensure faiss is non-None so the failure comes from embedding, not from missing faiss.
    monkeypatch.setattr(similarity_service, "faiss", object())
    monkeypatch.setattr(similarity_service, "_embedding_client", lambda: _FailingEmbeddingClient())
    monkeypatch.setattr(similarity_service, "_write_items", lambda kind, items: None)
    monkeypatch.setattr(similarity_service, "_save_embeddings", lambda kind, x: None)
    monkeypatch.setattr(
        similarity_service,
        "_meta_path",
        lambda kind: tmp_path / f"{kind}_meta.json",
    )

    logs: list[str] = []

    with pytest.raises(RuntimeError) as ctx:
        similarity_service.rebuild_similarity_global(log=logs.append)

    error_msg = str(ctx.value)
    expected_attempts = int(getattr(similarity_service, attempts_attr))

    assert f"failed after {expected_attempts} attempts" in error_msg.lower()
    assert f"[{error_label}]" in error_msg.lower()
    assert str(status_code) in error_msg

    if error_label == "transient":
        expected_sleeps = [similarity_service._backoff_delay(i) for i in range(expected_attempts - 1)]
    else:
        expected_sleeps = [similarity_service._STABLE_DELAY] * (expected_attempts - 1)
    assert sleep_calls == expected_sleeps

    # No meta files written: exception occurred before any successful embedding.
    assert not (tmp_path / "claim_meta.json").exists()
    assert not (tmp_path / "logic_meta.json").exists()

    # Retry progress logs should include attempt counters.
    assert any(f"attempt 1/{expected_attempts}" in line.lower() for line in logs)
    if expected_attempts > 1:
        assert any(
            f"attempt {expected_attempts - 1}/{expected_attempts}" in line.lower() for line in logs
        )
