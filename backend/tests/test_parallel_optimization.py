"""Tests for Phase 2+3: Parallel execution and global LLM concurrency control."""
from __future__ import annotations

import threading
import time

import pytest


class TestGlobalLLMSemaphore:
    """Test Phase 3: Global LLM concurrency semaphore in client.py."""

    def test_semaphore_lazy_init(self, monkeypatch):
        """Semaphore is lazily initialized from settings."""
        from app.llm import client

        # Reset global state
        monkeypatch.setattr(client, "_LLM_SEMAPHORE", None)
        monkeypatch.setattr(client.settings, "llm_global_max_concurrent", 4)

        sem = client._get_semaphore()
        assert isinstance(sem, threading.Semaphore)
        # Should return same instance on second call
        assert client._get_semaphore() is sem

    def test_semaphore_limits_concurrency(self, monkeypatch):
        """Semaphore limits concurrent LLM calls."""
        from app.llm import client

        monkeypatch.setattr(client, "_LLM_SEMAPHORE", None)
        monkeypatch.setattr(client.settings, "llm_global_max_concurrent", 2)

        max_concurrent = 0
        current_concurrent = 0
        lock = threading.Lock()

        original_invoke = None

        class MockLLM:
            def invoke(self, messages):
                nonlocal max_concurrent, current_concurrent
                with lock:
                    current_concurrent += 1
                    max_concurrent = max(max_concurrent, current_concurrent)
                time.sleep(0.05)
                with lock:
                    current_concurrent -= 1

                class Resp:
                    content = "test"
                return Resp()

        monkeypatch.setattr(client, "llm", lambda: MockLLM())

        threads = []
        for _ in range(6):
            t = threading.Thread(target=client.call_text, args=("sys", "usr"), kwargs={"use_retry": False})
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        assert max_concurrent <= 2


class TestGroundingCharBudget:
    """Test Phase 1.2: Character-budget batching for grounding."""

    def test_split_by_char_budget(self):
        from app.llm.grounding_judge_v2 import _split_by_char_budget

        items = [
            {"canonical_claim_id": f"c{i}", "chunk_text": "x" * 3000}
            for i in range(10)
        ]
        # Budget 10000 chars, max 20 per batch → ~3 items per batch
        batches = _split_by_char_budget(items, chars_max=10000, count_max=20)
        assert len(batches) >= 3
        for batch in batches:
            total_chars = sum(len(item["chunk_text"]) for item in batch)
            # First item in a batch can exceed budget (to avoid empty batches)
            if len(batch) > 1:
                assert total_chars <= 10000 + 3000  # tolerance for last item

    def test_split_respects_count_max(self):
        from app.llm.grounding_judge_v2 import _split_by_char_budget

        items = [
            {"canonical_claim_id": f"c{i}", "chunk_text": "x" * 100}
            for i in range(20)
        ]
        # Small char budget but count_max=5 should split into 4 batches
        batches = _split_by_char_budget(items, chars_max=999999, count_max=5)
        assert len(batches) == 4
        for batch in batches:
            assert len(batch) <= 5

    def test_empty_input(self):
        from app.llm.grounding_judge_v2 import _split_by_char_budget

        batches = _split_by_char_budget([], chars_max=10000, count_max=20)
        assert batches == []


class TestConflictCharBudget:
    """Test Phase 1.3: Character-budget batching for conflict judge."""

    def test_split_conflict_by_char_budget(self):
        from app.llm.conflict_judge import _split_conflict_by_char_budget

        pairs = [
            {"pair_id": f"p{i}", "claim_a": "x" * 500, "claim_b": "y" * 500}
            for i in range(10)
        ]
        batches = _split_conflict_by_char_budget(pairs, chars_max=5000, count_max=50)
        assert len(batches) >= 2
        for batch in batches:
            assert len(batch) <= 50

    def test_empty_pairs(self):
        from app.llm.conflict_judge import _split_conflict_by_char_budget

        batches = _split_conflict_by_char_budget([], chars_max=5000, count_max=50)
        assert batches == []


class TestSettingsParallelFields:
    """Test that new parallel config fields exist with correct defaults."""

    def test_parallel_settings_defaults(self):
        from app.settings import Settings

        s = Settings(
            _env_file=None,
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="test",
        )
        assert s.phase1_chunk_claim_max_workers == 4
        assert s.phase1_grounding_max_workers == 2
        assert s.phase2_conflict_max_workers == 3
        assert s.ingest_pre_llm_max_workers == 4
        assert s.faiss_embed_max_workers == 3
        assert s.llm_global_max_concurrent == 16


class TestBatchSchemas:
    """Test new Pydantic schemas for batch extraction."""

    def test_chunk_claims_batch_response_parse(self):
        from app.llm.schemas import ChunkClaimsBatchResponse

        data = {
            "chunks": [
                {
                    "chunk_id": "c0",
                    "claims": [
                        {"text": "claim1", "evidence_quote": "quote1", "step_type": "Method"},
                    ],
                },
                {"chunk_id": "c1", "claims": []},
            ]
        }
        resp = ChunkClaimsBatchResponse.model_validate(data)
        assert len(resp.chunks) == 2
        assert resp.chunks[0].chunk_id == "c0"
        assert len(resp.chunks[0].claims) == 1
        assert resp.chunks[1].chunk_id == "c1"
        assert len(resp.chunks[1].claims) == 0

    def test_chunk_claims_batch_response_empty(self):
        from app.llm.schemas import ChunkClaimsBatchResponse

        resp = ChunkClaimsBatchResponse.model_validate({"chunks": []})
        assert len(resp.chunks) == 0
