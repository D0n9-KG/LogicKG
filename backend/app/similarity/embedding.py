"""Embedding generation utilities for semantic similarity workflows."""
from __future__ import annotations

import requests

from app.settings import settings


def get_embeddings_batch(texts: list[str], model: str | None = None) -> list[list[float]]:
    """
    Generate embeddings for a batch of texts using OpenAI-compatible API.

    Uses requests library instead of OpenAI SDK for better compatibility
    with local embedding services like GPUStack.

    Args:
        texts: List of text strings to embed.
        model: Embedding model name (default: from settings or text-embedding-3-small)

    Returns:
        List of embedding vectors (each is list of floats)

    Raises:
        RuntimeError: If API call fails after retries
    """
    import time

    if not texts:
        return []

    # Resolve model + credentials from shared settings abstraction
    model = model or settings.effective_embedding_model() or "text-embedding-3-small"
    api_key = settings.effective_embedding_api_key()
    if not api_key:
        raise ValueError("Embedding API key is not configured")
    base_url = settings.effective_embedding_base_url()

    # Prepare request
    url = f"{base_url}/embeddings" if base_url else "https://api.openai.com/v1/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "input": texts,
    }

    # Retry logic for transient errors
    max_retries = 3
    retry_delay = 5  # seconds

    def _is_retryable_error(exc: Exception) -> bool:
        """Check if error is retryable (transient)."""
        if isinstance(exc, requests.exceptions.HTTPError):
            status_code = exc.response.status_code if exc.response else None
            if isinstance(status_code, int):
                return status_code in {408, 429, 500, 502, 503, 504}
        error_text = str(exc).lower()
        transient_signals = (
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
        return any(signal in error_text for signal in transient_signals)

    # Make API call with retry
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()

            # Parse response
            try:
                data = response.json()
                embeddings = [item["embedding"] for item in data["data"]]
                return embeddings
            except (KeyError, TypeError, ValueError) as e:
                raise RuntimeError(f"Embedding API response parse error: {str(e)}")

        except requests.exceptions.HTTPError as e:
            error_msg = f"Embedding API error {e.response.status_code}: {e.response.text[:500]}"
            retryable = _is_retryable_error(e)
            if retryable and attempt < max_retries - 1:
                print(f"Clustering embedding attempt {attempt + 1}/{max_retries} failed: {error_msg}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                reason = (
                    f"non-retryable HTTP error on attempt {attempt + 1}/{max_retries}"
                    if not retryable
                    else f"embedding unavailable after {max_retries} attempts"
                )
                raise RuntimeError(f"Clustering embedding failed: {reason}. Error: {error_msg}")

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                print(f"Clustering embedding attempt {attempt + 1}/{max_retries} timed out. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                raise RuntimeError(f"Clustering embedding failed: timeout after {max_retries} attempts (120s each)")

        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            retryable = _is_retryable_error(e)
            if retryable and attempt < max_retries - 1:
                print(f"Clustering embedding attempt {attempt + 1}/{max_retries} failed: {error_msg}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                reason = (
                    f"non-retryable request error on attempt {attempt + 1}/{max_retries}"
                    if not retryable
                    else f"embedding unavailable after {max_retries} attempts"
                )
                raise RuntimeError(f"Clustering embedding failed: {reason}. Error: {error_msg}")

    # Should never reach here, but defensive
    raise RuntimeError("Clustering embedding failed: retry loop exited without success or error")


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    import math

    if len(vec_a) != len(vec_b):
        raise ValueError("Vectors must have same dimension")

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)
