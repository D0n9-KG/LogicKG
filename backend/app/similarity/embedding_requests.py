"""
Alternative embedding implementation using requests library for GPUStack compatibility.

Use this instead of OpenAI SDK when encountering 502 errors with GPUStack.
"""
from __future__ import annotations

import requests

from app.settings import settings


def get_embeddings_batch_requests(texts: list[str], model: str | None = None) -> list[list[float]]:
    """
    Generate embeddings using requests library (GPUStack compatible).

    This is an alternative to the OpenAI SDK implementation that works
    better with local GPUStack services that may have SDK compatibility issues.

    Args:
        texts: List of text strings to embed.
        model: Embedding model name (default: from settings)

    Returns:
        List of embedding vectors (each is list of floats)

    Raises:
        RuntimeError: If API call fails
    """
    if not texts:
        return []

    # Resolve configuration
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

    # Make API call
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=120)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Embedding API error {e.response.status_code}: {e.response.text[:500]}")
    except requests.exceptions.Timeout:
        raise RuntimeError("Embedding API timeout after 120s")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Embedding API request failed: {str(e)}")

    # Parse response
    try:
        data = response.json()
        embeddings = [item["embedding"] for item in data["data"]]
        return embeddings
    except (KeyError, TypeError, ValueError) as e:
        raise RuntimeError(f"Embedding API response parse error: {str(e)}")


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
