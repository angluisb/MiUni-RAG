from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from time import perf_counter
from uuid import uuid4

from app.core.config import Settings
from app.rag.embeddings import DenseEmbedder, LocalReranker
from app.rag.models import RetrievalResult, SearchHit
from app.rag.repository import RagRepository

logger = logging.getLogger("uvicorn.error.rag")


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
        query_text = question
        if settings.RAG_HYDE_ENABLED and hyde_generator:
            stage = perf_counter()
            try:
                hypothetical = await asyncio.wait_for(
                    hyde_generator(question), timeout=settings.RAG_HYDE_TIMEOUT_SECONDS)
                if hypothetical.strip():
                    query_text = hypothetical.strip()
                    metrics["hyde_used"] = True
            except Exception:
                # HyDE is an enhancement; an unavailable LLM must not prevent retrieval.
                metrics["hyde_failed"] = True
                logger.warning("HyDE fallo; se recuperara usando la pregunta original")
            metrics["hyde_ms"] = (perf_counter() - stage) * 1000

        async def timed_call(key, fn, *args):
            stage = perf_counter()
            result = await asyncio.to_thread(fn, *args)
            metrics[key] = (perf_counter() - stage) * 1000
            return result

        async def vector_branch():
            embeddings = await timed_call("embedding_ms", self.embedder.encode, [query_text])
            return await timed_call("vector_search_ms", self.repository.vector_search,
                                    embeddings[0], settings.RAG_VECTOR_TOP_N)

        if settings.RAG_HYBRID_SEARCH_ENABLED:
            vector, lexical = await asyncio.gather(
                vector_branch(),
                timed_call("lexical_search_ms", self.repository.lexical_search,
                           question, settings.RAG_LEXICAL_TOP_N),
            )
            stage = perf_counter()
            hits = reciprocal_rank_fusion([vector, lexical], settings.RAG_RRF_K)
            metrics["rrf_ms"] = (perf_counter() - stage) * 1000
        else:
            hits = await vector_branch()
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
