from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests
from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import Embeddings

from app.ingest.models import Chunk
from app.settings import settings

_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_TRANSIENT_ERROR_SIGNALS = (
    "502", "503", "504", "timeout", "timed out",
    "connection reset", "connection aborted",
    "temporarily unavailable", "rate limit",
)


def _is_retryable_embedding_error(exc: Exception) -> bool:
    """Return True if the embedding error is transient and worth retrying."""
    if isinstance(exc, requests.exceptions.HTTPError):
        status_code = exc.response.status_code if exc.response else None
        if isinstance(status_code, int):
            return status_code in _TRANSIENT_STATUS_CODES

    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code in _TRANSIENT_STATUS_CODES

    error_text = str(exc).lower()
    return any(signal in error_text for signal in _TRANSIENT_ERROR_SIGNALS)


class _RequestsEmbeddings(Embeddings):
    """Direct requests-based embedding client for OpenAI-compatible providers.

    Bypasses the OpenAI Python SDK to avoid compatibility issues that cause 502
    errors with certain providers:
    - SDK sends tokenized input arrays by default (check_embedding_ctx_length=True)
    - SDK defaults to encoding_format="base64" when not specified
    - SDK injects X-Stainless-* headers that some providers reject

    This adapter sends a minimal JSON payload: {"model": ..., "input": [str, ...]}
    identical to what the clustering path (app/similarity/embedding.py) uses.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        model: str,
        chunk_size: int = 64,
        max_retries: int = 0,
        timeout_seconds: int = 120,
    ) -> None:
        self._model = model
        self._chunk_size = max(1, int(chunk_size))
        self._max_retries = max(0, int(max_retries))
        self._timeout = max(1, int(timeout_seconds))

        base = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._url = f"{base}/embeddings"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a single batch with optional retry logic."""
        payload: dict[str, Any] = {"model": self._model, "input": texts}
        last_exc: Exception = RuntimeError("unknown error")

        for attempt in range(self._max_retries + 1):
            try:
                response = requests.post(
                    self._url,
                    headers=self._headers,
                    json=payload,
                    timeout=self._timeout,
                )
                response.raise_for_status()
                data = response.json()
                vectors: list[list[float]] = [item["embedding"] for item in data["data"]]
                if len(vectors) != len(texts):
                    raise RuntimeError(
                        f"Embedding response count mismatch: "
                        f"sent {len(texts)}, received {len(vectors)}"
                    )
                return vectors

            except requests.exceptions.HTTPError as exc:
                last_exc = exc
            except requests.exceptions.RequestException as exc:
                # Covers Timeout, ConnectionError, and other transient network errors
                last_exc = exc
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"Embedding API response parse error: {exc}") from exc

            is_retryable = _is_retryable_embedding_error(last_exc)
            is_last_attempt = attempt >= self._max_retries
            if is_retryable and not is_last_attempt:
                delay = 5 * (2 ** attempt)  # exponential backoff: 5s, 10s, 20s, ...
                time.sleep(delay)
            else:
                reason = (
                    "non-retryable error" if not is_retryable
                    else f"failed after {attempt + 1} attempts"
                )
                raise RuntimeError(
                    f"Embedding request failed ({reason}). Error: {last_exc}"
                ) from last_exc

        raise AssertionError("unreachable")  # pragma: no cover

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self._chunk_size):
            vectors.extend(self._embed_batch(texts[i : i + self._chunk_size]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text])[0]


def _create_provider_compatible_embeddings(*, max_retries: int | None = None) -> Embeddings:
    """Create requests-based embeddings client that bypasses OpenAI SDK incompatibilities.

    Args:
        max_retries: Number of internal retries per batch.
                     None = use default (2 retries, 3 total attempts).
                     0 = disable internal retries (use when caller handles retries).

    Returns:
        Configured _RequestsEmbeddings instance.
    """
    api_key = settings.effective_embedding_api_key()
    base_url = settings.effective_embedding_base_url()
    model = settings.effective_embedding_model()
    if not model:
        raise RuntimeError("EMBEDDING_MODEL is not set; FAISS disabled")
    if not api_key:
        raise RuntimeError(
            "Embedding API key is required to build FAISS index "
            "(set EMBEDDING_PROVIDER=siliconflow and SILICONFLOW_API_KEY)"
        )

    effective_retries = 2 if max_retries is None else max(0, int(max_retries))
    return _RequestsEmbeddings(
        api_key=api_key,
        base_url=base_url,
        model=model,
        chunk_size=64,
        max_retries=effective_retries,
    )


def build_faiss_for_chunks(chunks: list[Chunk], out_dir: str) -> dict:
    if not chunks:
        raise RuntimeError("FAISS index build failed: no chunks available to index")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Disable internal retries: outer batch-level retry (5×) handles transient errors.
    embeddings = _create_provider_compatible_embeddings(max_retries=0)

    texts = [c.text for c in chunks]
    metadatas = [
        {
            "chunk_id": c.chunk_id,
            "paper_source": c.paper_source,
            "md_path": c.md_path,
            "start_line": c.span.start_line,
            "end_line": c.span.end_line,
            "section": c.section,
            "kind": c.kind,
        }
        for c in chunks
    ]

    # ── Phase 2.5: Dual-stage embed parallelization ──
    # Stage 1: Parallel embedding computation
    # Stage 2: Serial FAISS index construction (not thread-safe)

    batch_size = 64
    max_batch_retries = 5
    base_retry_delay = 5  # seconds (exponential backoff: 5, 10, 20, 40, 80)
    total_batches = (len(texts) + batch_size - 1) // batch_size

    def _embed_one_batch(batch_idx: int) -> tuple[int, list[list[float]]]:
        """Embed a single batch with retry logic. Returns (batch_idx, vectors)."""
        start = batch_idx * batch_size
        end = min(start + batch_size, len(texts))
        batch_texts = texts[start:end]

        for attempt in range(max_batch_retries):
            try:
                vectors = embeddings.embed_documents(batch_texts)
                return batch_idx, vectors
            except Exception as exc:
                error_msg = str(exc).strip()
                retryable = _is_retryable_embedding_error(exc)
                retry_delay = base_retry_delay * (2 ** attempt)
                if retryable and attempt < max_batch_retries - 1:
                    print(
                        f"FAISS embed batch {batch_idx + 1}/{total_batches} "
                        f"attempt {attempt + 1}/{max_batch_retries} failed: {error_msg}. "
                        f"Retrying in {retry_delay}s..."
                    )
                    time.sleep(retry_delay)
                else:
                    reason = (
                        f"non-retryable embedding error at batch {batch_idx + 1}/{total_batches}, "
                        f"attempt {attempt + 1}/{max_batch_retries}"
                        if not retryable
                        else f"embedding unavailable at batch {batch_idx + 1}/{total_batches} "
                        f"after {max_batch_retries} attempts"
                    )
                    raise RuntimeError(
                        f"FAISS index build failed: {reason}. "
                        f"Error: {error_msg}. Please check embedding API configuration and try again."
                    ) from exc

        raise AssertionError("unreachable")  # pragma: no cover

    # Stage 1: Parallel embedding
    from concurrent.futures import ThreadPoolExecutor

    embed_workers = min(settings.faiss_embed_max_workers, total_batches)
    embed_workers = max(1, embed_workers)

    all_vectors: list[tuple[int, list[list[float]]]] = []
    if embed_workers == 1 or total_batches <= 1:
        for bi in range(total_batches):
            all_vectors.append(_embed_one_batch(bi))
            print(f"Embed batch {bi + 1}/{total_batches} completed")
    else:
        with ThreadPoolExecutor(max_workers=embed_workers) as executor:
            futures = {executor.submit(_embed_one_batch, bi): bi for bi in range(total_batches)}
            for future in futures:
                bi = futures[future]
                idx, vectors = future.result()  # propagate exceptions
                all_vectors.append((idx, vectors))
                print(f"Embed batch {idx + 1}/{total_batches} completed")

    # Sort by batch index for deterministic ordering
    all_vectors.sort(key=lambda x: x[0])

    # Stage 2: Serial FAISS index construction
    store = None
    for batch_idx, vectors in all_vectors:
        start = batch_idx * batch_size
        end = min(start + batch_size, len(texts))
        batch_texts = texts[start:end]
        batch_metadatas = metadatas[start:end]
        text_embeddings = list(zip(batch_texts, vectors))

        if store is None:
            store = FAISS.from_embeddings(
                text_embeddings=text_embeddings,
                embedding=embeddings,
                metadatas=batch_metadatas,
            )
        else:
            store.add_embeddings(text_embeddings=text_embeddings, metadatas=batch_metadatas)

    if store is None:
        raise RuntimeError("FAISS index build failed: no embeddings produced")
    store.save_local(str(out))
    return {"chunks_indexed": len(chunks), "dir": str(out)}


def load_faiss(out_dir: str) -> FAISS:
    # Keep default retries (max_retries=None → 2 internal retries) for online query resilience.
    embeddings = _create_provider_compatible_embeddings()
    return FAISS.load_local(out_dir, embeddings, allow_dangerous_deserialization=True)
