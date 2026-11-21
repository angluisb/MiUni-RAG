"""HyDE enriches retrieval without replacing the original dense signal."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from app.core.config import Settings
from app.rag.models import SearchHit
from app.rag.retrieval import RetrievalService


class RawQueryAnchorTests(unittest.IsolatedAsyncioTestCase):
    def service(self, **overrides):
        values = Settings(_env_file=None).model_dump()
        values.update(RAG_HYDE_ENABLED=True, RAG_HYBRID_SEARCH_ENABLED=True,
                      RAG_RERANK_ENABLED=False, RAG_TEMPORAL_FILTER_ENABLED=False,
                      RAG_CONTEXT_TOP_K=2, RAG_MEASURE_RETRIEVAL_PERFORMANCE=False,
                      RAG_CACHE_MAX_ENTRIES=128, RAG_EMBEDDING_CACHE_TTL_SECONDS=600,
                      RAG_HYDE_CACHE_TTL_SECONDS=120)
        values.update(overrides)
        repository = Mock()
        repository.lexical_search.return_value = []
        embedder = Mock()
        embedder.encode.side_effect = lambda texts: [[1.0] if text == "practices requirements" else [2.0] for text in texts]
        relevant = SearchHit("z-practices", "https://unison.mx/practices", "Practices regulation", "rules", {}, 0.9)
        unrelated = [SearchHit(f"a-degree-{i}", "https://unison.mx/degrees", "Degrees", "program", {}, 0.9)
                     for i in range(6)]
        repository.vector_search.side_effect = lambda embedding, *args: [relevant] if embedding == [1.0] else unrelated
        return RetrievalService(SimpleNamespace(**values), repository, embedder, Mock())

    async def test_irrelevant_hyde_cannot_remove_raw_dense_relevant_hit(self):
        service = self.service()
        generator = AsyncMock(return_value="unrelated degree programs")
        result = await service.retrieve("practices requirements", generator)
        self.assertIn("z-practices", [hit.id for hit in result.chunks])
        self.assertEqual(service.repository.vector_search.call_count, 2)
        service.embedder.encode.assert_has_calls([call(["practices requirements"]), call(["unrelated degree programs"])], any_order=True)
        service.repository.lexical_search.assert_called_once_with("practices requirements", service.settings.RAG_LEXICAL_TOP_N)

    async def test_both_embeddings_cache_independently_and_private_requests_bypass(self):
        service = self.service()
        generator = AsyncMock(return_value="unrelated degree programs")
        first = await service.retrieve("practices requirements", generator)
        second = await service.retrieve("practices requirements", generator)
        self.assertEqual(first.metrics["embedding_cache"], "miss")
        self.assertEqual(second.metrics["embedding_cache"], "hit")
        self.assertEqual(service.embedder.encode.call_count, 2)
        generator.assert_awaited_once()
        for _ in range(2):
            private = await service.retrieve("practices requirements", generator, private_context=True)
            self.assertEqual(private.metrics["embedding_cache"], "disabled")
        self.assertEqual(service.embedder.encode.call_count, 6)

    async def test_raw_temporal_policy_is_applied_to_both_dense_searches(self):
        service = self.service(RAG_TEMPORAL_FILTER_ENABLED=True)
        generator = AsyncMock(return_value=json.dumps({"alcance_temporal": "historico", "periodo": None,
                                                       "hyde_doc": "unrelated degree programs"}))
        result = await service.retrieve("practices requirements", generator,
                                        temporal_question="current requirements", private_context=True)
        self.assertEqual(result.metrics["temporal_scope"], "vigente")
        self.assertEqual(len(service.repository.vector_search.call_args_list), 2)
        for invocation in service.repository.vector_search.call_args_list:
            self.assertEqual(invocation.args[2].scope, "vigente")

    async def test_failed_or_disabled_hyde_keeps_single_raw_dense_search(self):
        for enabled in (True, False):
            service = self.service(RAG_HYDE_ENABLED=enabled)
            result = await service.retrieve("practices requirements", AsyncMock(side_effect=TimeoutError()))
            self.assertIn("z-practices", [hit.id for hit in result.chunks])
            service.embedder.encode.assert_called_once_with(["practices requirements"])
            self.assertEqual(service.repository.vector_search.call_count, 1)

    async def test_identical_hypothesis_does_not_repeat_dense_work(self):
        service = self.service()
        await service.retrieve("practices requirements", AsyncMock(return_value="practices requirements"))
        service.embedder.encode.assert_called_once_with(["practices requirements"])
        self.assertEqual(service.repository.vector_search.call_count, 1)

    async def test_cancellation_drains_all_branch_awaiters(self):
        service = self.service()
        ready, gate = asyncio.Event(), asyncio.Event()
        started, cancelled = [], []

        async def controlled(fn, *args):
            started.append(fn)
            if len(started) == 3:
                ready.set()
            try:
                await gate.wait()
            except asyncio.CancelledError:
                cancelled.append(fn)
                raise

        before = set(asyncio.all_tasks())
        with patch("app.rag.retrieval.asyncio.to_thread", controlled):
            task = asyncio.create_task(service.retrieve("practices requirements", AsyncMock(return_value="unrelated")))
            await asyncio.wait_for(ready.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.sleep(0)
        self.assertEqual(len(cancelled), 3)
        self.assertFalse([task for task in asyncio.all_tasks() - before if not task.done()])
