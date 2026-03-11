from __future__ import annotations

from typing import Iterable

import numpy as np

from app.similarity.embedding import get_embeddings_batch


class _TensorLike:
    def __init__(self, values: Iterable[float]) -> None:
        self._values = np.asarray(list(values), dtype=float)

    def cpu(self) -> "_TensorLike":
        return self

    def numpy(self) -> np.ndarray:
        return self._values


class SentenceTransformer:
    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name

    def _embedding_model(self) -> str | None:
        model_name = str(self.model_name or "").strip()
        if model_name in {"", "all-MiniLM-L6-v2", "sentence-transformers/all-MiniLM-L6-v2"}:
            return None
        return model_name

    def encode(self, sentences, convert_to_tensor: bool = False, batch_size: int = 32):
        single_input = isinstance(sentences, str)
        texts = [sentences] if single_input else [str(item or "") for item in sentences]
        normalized_texts = [text[:4000] for text in texts]
        embeddings = []
        chunk_size = max(1, min(int(batch_size or 8), 8))
        for index in range(0, len(normalized_texts), chunk_size):
            embeddings.extend(
                get_embeddings_batch(
                    normalized_texts[index:index + chunk_size],
                    model=self._embedding_model(),
                )
            )
        if convert_to_tensor:
            tensors = [_TensorLike(values) for values in embeddings]
            return tensors[0] if single_input else tensors
        if single_input:
            return np.asarray(embeddings[0], dtype=float)
        return np.asarray(embeddings, dtype=float)
