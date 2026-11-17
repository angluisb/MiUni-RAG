from __future__ import annotations

import asyncio
import json
import logging
import unicodedata
from dataclasses import replace
from time import perf_counter
from uuid import uuid4

from app.core.config import Settings
from app.rag.cache import TTLCache
from app.rag.embeddings import DenseEmbedder, LocalReranker
from app.rag.models import RetrievalResult, SearchHit
from app.rag.repository import RagRepository

logger = logging.getLogger("uvicorn.error.rag")


def _normalized_cache_input(text: str) -> str:
    # Preserve accents, punctuation, digits and word boundaries.
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def reciprocal_rank_fusion(rankings: list[list[SearchHit]], k: int = 60) -> list[SearchHit]:
    if k < 1:
        raise ValueError("RRF k debe ser positivo")
    scores: dict[str, float] = {}
    hits = {}
    for ranking in rankings:
        seen = set()
        for rank, hit in enumerate(ranking, 1):
            if hit.id in seen:
                continue
            seen.add(hit.id)
            hits.setdefault(hit.id, hit)
            scores[hit.id] = scores.get(hit.id, 0.0) + 1.0 / (k + rank)
    return [replace(hits[key], score=scores[key])
            for key in sorted(scores, key=lambda key: (-scores[key], key))]


class RetrievalService:
    def __init__(self, settings: Settings, repository=None, embedder=None, reranker=None):
        self.settings = settings
        self.repository = repository or RagRepository(settings)
        self.embedder = embedder or DenseEmbedder(settings)
        self.reranker = reranker or LocalReranker(settings)
        capacity = getattr(settings, "RAG_CACHE_MAX_ENTRIES", 128)
        self._hyde_cache = TTLCache(
            capacity, getattr(settings, "RAG_HYDE_CACHE_TTL_SECONDS", 120))
        self._embedding_cache = TTLCache(
            capacity, getattr(settings, "RAG_EMBEDDING_CACHE_TTL_SECONDS", 600))

    async def retrieve(self, question: str, hyde_generator=None) -> RetrievalResult:
        settings = self.settings
        started = perf_counter()
        metrics = {"question_id": str(uuid4()), "experiment_name": settings.RAG_EXPERIMENT_NAME,
                   "hyde_enabled": settings.RAG_HYDE_ENABLED, "hyde_used": False,
                   "hybrid_enabled": settings.RAG_HYBRID_SEARCH_ENABLED,
                   "rerank_enabled": settings.RAG_RERANK_ENABLED,
                   "hyde_ms": 0.0, "embedding_ms": 0.0, "vector_search_ms": 0.0,
                   "lexical_search_ms": 0.0, "rrf_ms": 0.0, "rerank_ms": 0.0,
                   "vector_top_n": settings.RAG_VECTOR_TOP_N,
                   "lexical_top_n": settings.RAG_LEXICAL_TOP_N,
                   "context_top_k": settings.RAG_CONTEXT_TOP_K}
        hyde_cache_enabled = (getattr(settings, "RAG_CACHE_MAX_ENTRIES", 128) > 0
                              and self._hyde_cache.ttl_seconds > 0)
        embedding_cache_enabled = (getattr(settings, "RAG_CACHE_MAX_ENTRIES", 128) > 0
                                   and self._embedding_cache.ttl_seconds > 0)
        metrics["hyde_cache"] = "disabled"
        metrics["embedding_cache"] = "miss" if embedding_cache_enabled else "disabled"

        async def timed_call(key, fn, *args):
            stage = perf_counter()
            result = await asyncio.to_thread(fn, *args)
            metrics[key] = (perf_counter() - stage) * 1000
            return result

        query_text = question
        async def vector_branch():
            embedding_key = (_normalized_cache_input(query_text), settings.RAG_EMBEDDING_MODEL,
                             settings.RAG_EMBEDDING_PIPELINE_VERSION)
            embedding = self._embedding_cache.get(embedding_key) if embedding_cache_enabled else None
            if embedding is not None:
                metrics["embedding_cache"] = "hit"
            else:
                embeddings = await timed_call("embedding_ms", self.embedder.encode, [query_text])
                embedding = embeddings[0]
                if embedding_cache_enabled and embedding is not None and len(embedding):
                    self._embedding_cache.put(embedding_key, embedding)
            return await timed_call("vector_search_ms", self.repository.vector_search,
                                    embedding, settings.RAG_VECTOR_TOP_N)

        tasks = []
        try:
            lexical_task = None
            if settings.RAG_HYBRID_SEARCH_ENABLED:
                lexical_task = asyncio.create_task(
                    timed_call("lexical_search_ms", self.repository.lexical_search,
                               question, settings.RAG_LEXICAL_TOP_N))
                tasks.append(lexical_task)
            if settings.RAG_HYDE_ENABLED and hyde_generator:
                stage = perf_counter()
                hyde_key = (_normalized_cache_input(question), settings.LLM_MODEL,
                            settings.RAG_EMBEDDING_PIPELINE_VERSION,
                            getattr(settings, "RAG_HYDE_PROMPT_VERSION", "hyde-v1"),
                            settings.RAG_HYDE_SENTENCES)
                hypothetical = self._hyde_cache.get(hyde_key) if hyde_cache_enabled else None
                if hyde_cache_enabled:
                    metrics["hyde_cache"] = "hit" if hypothetical is not None else "miss"
                try:
                    if hypothetical is None:
                        hypothetical = await asyncio.wait_for(
                            hyde_generator(question), timeout=settings.RAG_HYDE_TIMEOUT_SECONDS)
                    if not isinstance(hypothetical, str):
                        raise ValueError("HyDE returned non-text content")
                    if hypothetical.strip():
                        query_text = hypothetical.strip()
                        metrics["hyde_used"] = True
                        if hyde_cache_enabled:
                            self._hyde_cache.put(hyde_key, hypothetical.strip())
                except Exception:
                    # HyDE is optional; provider failure preserves the original query.
                    metrics["hyde_failed"] = True
                    logger.warning("HyDE fallo; se recuperara usando la pregunta original")
                metrics["hyde_ms"] = (perf_counter() - stage) * 1000

            vector_task = asyncio.create_task(vector_branch())
            tasks.append(vector_task)
            if lexical_task is not None:
                vector, lexical = await asyncio.gather(vector_task, lexical_task)
                stage = perf_counter()
                hits = reciprocal_rank_fusion([vector, lexical], settings.RAG_RRF_K)
                metrics["rrf_ms"] = (perf_counter() - stage) * 1000
            else:
                hits = await vector_task
        finally:
            # Cancelling to_thread's awaiter cannot stop the underlying SQL/model
            # thread. Database statement timeouts still bound outstanding SQL.
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        if settings.RAG_RERANK_ENABLED:
            hits = await timed_call("rerank_ms", self.reranker.rerank, question, hits)
        hits = hits[:settings.RAG_CONTEXT_TOP_K]
        metrics["total_retrieval_ms"] = (perf_counter() - started) * 1000
        metrics["returned_chunk_ids"] = [hit.id for hit in hits]
        metrics["returned_source_urls"] = list(dict.fromkeys(hit.source_url for hit in hits))
        if settings.RAG_MEASURE_RETRIEVAL_PERFORMANCE:
            logger.info("rag_retrieval %s", json.dumps(metrics, ensure_ascii=False))
        if settings.RAG_LOG_RETRIEVAL_RESULTS:
            logger.info("rag_results %s", json.dumps([
                {"id": hit.id, "score": hit.score, "source_url": hit.source_url} for hit in hits]))
        if settings.RAG_LOG_CONTEXT_CHUNKS:
            logger.info("rag_context %s", json.dumps([
                {"id": hit.id, "content": hit.content} for hit in hits], ensure_ascii=False))
        return RetrievalResult(hits, metrics)


def format_context(chunks: list[SearchHit]) -> str:
    # JSON encoding keeps source content delimited even when it contains markup.
    return json.dumps([
        {"citation": index, "title": chunk.document_title, "url": chunk.source_url,
         "page_start": chunk.metadata.get("page_start"),
         "page_end": chunk.metadata.get("page_end"), "content": chunk.content}
        for index, chunk in enumerate(chunks, 1)
    ], ensure_ascii=False)
