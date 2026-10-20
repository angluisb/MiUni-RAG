from __future__ import annotations

import math
from threading import Lock

from app.core.config import Settings


def vector_literal(values, dimension: int = 1024) -> str:
    numbers = [float(value) for value in values]
    if len(numbers) != dimension or not all(math.isfinite(value) for value in numbers):
        raise ValueError(f"El embedding debe tener {dimension} valores finitos")
    if not any(numbers):
        raise ValueError("El embedding no puede ser un vector cero para similitud coseno")
    return "[" + ",".join(str(value) for value in numbers) + "]"


class DenseEmbedder:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None
        self._lock = Lock()

    def encode(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        # Loading and inference are serialized to bound CPU/GPU memory across requests.
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(
                    self.settings.RAG_EMBEDDING_MODEL,
                    device=self.settings.RAG_MODEL_DEVICE,
                    cache_folder=self.settings.RAG_MODEL_CACHE,
                )
                if self._model.get_embedding_dimension() != 1024:
                    raise ValueError("El modelo no coincide con rag_chunk.embedding vector(1024)")
            vectors = self._model.encode(
                texts,
                batch_size=self.settings.RAG_EMBEDDING_BATCH_SIZE,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        return [vector_literal(vector) for vector in vectors]


class LocalReranker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None
        self._lock = Lock()

    def rerank(self, question, hits):
        if not hits:
            return []
        with self._lock:
            if self._model is None:
                from sentence_transformers import CrossEncoder

                self._model = CrossEncoder(
                    self.settings.RAG_RERANK_MODEL,
                    device=self.settings.RAG_MODEL_DEVICE,
                    cache_folder=self.settings.RAG_MODEL_CACHE,
                )
            scores = self._model.predict(
                [(question, hit.content) for hit in hits],
                batch_size=self.settings.RAG_EMBEDDING_BATCH_SIZE,
                show_progress_bar=False,
            )
        return [hit for _, hit in sorted(zip(scores, hits), key=lambda pair: -float(pair[0]))]
