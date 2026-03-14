from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests
from langchain_community.vectorstores import FAISS
from langchain_core.embeddings import Embeddings

from app.ingest.models import Chunk
from app.ops_config_store import merge_runtime_config
from app.settings import settings

_TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}
_TRANSIENT_ERROR_SIGNALS = (
    "502",
    "503",
    "504",
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "temporarily unavailable",
    "rate limit",
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
    """Direct requests-based embedding client for OpenAI-compatible providers."""

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
                        f"Embedding response count mismatch: sent {len(texts)}, received {len(vectors)}"
                    )
                return vectors
            except requests.exceptions.HTTPError as exc:
                last_exc = exc
            except requests.exceptions.RequestException as exc:
                last_exc = exc
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(f"Embedding API response parse error: {exc}") from exc

            is_retryable = _is_retryable_embedding_error(last_exc)
            is_last_attempt = attempt >= self._max_retries
            if is_retryable and not is_last_attempt:
                delay = 5 * (2 ** attempt)
                time.sleep(delay)
            else:
                reason = "non-retryable error" if not is_retryable else f"failed after {attempt + 1} attempts"
                raise RuntimeError(
                    f"Embedding request failed ({reason}). Error: {last_exc}"
                ) from last_exc

        raise AssertionError("unreachable")

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
    """Create requests-based embeddings client that bypasses OpenAI SDK incompatibilities."""
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


def _build_faiss_from_texts(
    *,
    texts: list[str],
    metadatas: list[dict[str, Any]],
    out_dir: str,
) -> None:
    if not texts:
        raise RuntimeError("FAISS index build failed: no rows available to index")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    embeddings = _create_provider_compatible_embeddings(max_retries=0)

    batch_size = 64
    max_batch_retries = 5
    base_retry_delay = 5
    total_batches = (len(texts) + batch_size - 1) // batch_size

    def _embed_one_batch(batch_idx: int) -> tuple[int, list[list[float]]]:
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

        raise AssertionError("unreachable")

    from concurrent.futures import ThreadPoolExecutor

    runtime = merge_runtime_config({})
    embed_workers = max(1, min(int(runtime.get("faiss_embed_max_workers") or settings.faiss_embed_max_workers), total_batches))
    all_vectors: list[tuple[int, list[list[float]]]] = []
    if embed_workers == 1 or total_batches <= 1:
        for bi in range(total_batches):
            all_vectors.append(_embed_one_batch(bi))
            print(f"Embed batch {bi + 1}/{total_batches} completed")
    else:
        with ThreadPoolExecutor(max_workers=embed_workers) as executor:
            futures = {executor.submit(_embed_one_batch, bi): bi for bi in range(total_batches)}
            for future in futures:
                idx, vectors = future.result()
                all_vectors.append((idx, vectors))
                print(f"Embed batch {idx + 1}/{total_batches} completed")

    all_vectors.sort(key=lambda x: x[0])

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


def build_faiss_for_rows(
    rows: list[dict[str, Any]],
    out_dir: str,
    *,
    text_key: str,
    metadata_keys: list[str],
) -> dict[str, Any]:
    texts: list[str] = []
    metadatas: list[dict[str, Any]] = []
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = str(row.get(text_key) or "").strip()
        if not text:
            continue
        texts.append(text)
        metadatas.append({key: row.get(key) for key in metadata_keys if key in row})
        count += 1

    _build_faiss_from_texts(texts=texts, metadatas=metadatas, out_dir=out_dir)
    return {"rows_indexed": count, "dir": str(Path(out_dir))}


def build_faiss_for_chunks(chunks: list[Chunk], out_dir: str) -> dict:
    rows = [
        {
            "text": c.text,
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
    res = build_faiss_for_rows(
        rows,
        out_dir,
        text_key="text",
        metadata_keys=[
            "chunk_id",
            "paper_source",
            "md_path",
            "start_line",
            "end_line",
            "section",
            "kind",
        ],
    )
    return {"chunks_indexed": res["rows_indexed"], "dir": res["dir"]}


def load_faiss(out_dir: str) -> FAISS:
    target_dir = Path(out_dir)
    if target_dir.is_dir() and (target_dir / "chunks").is_dir() and not (target_dir / "index.faiss").exists():
        target_dir = target_dir / "chunks"
    embeddings = _create_provider_compatible_embeddings()
    return FAISS.load_local(str(target_dir), embeddings, allow_dangerous_deserialization=True)
