import asyncio
from concurrent.futures import ThreadPoolExecutor
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from app.core.config import Settings
from app.rag.cache import TTLCache
from app.rag.retrieval import RetrievalService


class TTLCacheTests(unittest.TestCase):
    def test_ttl_lru_capacity_and_clear(self):
        with patch("app.rag.cache.monotonic", return_value=0) as clock:
            cache = TTLCache(max_entries=2, ttl_seconds=10)
            cache.put("a", 1)
            cache.put("b", 2)
            self.assertEqual(cache.get("a"), 1)
            cache.put("c", 3)
            self.assertIsNone(cache.get("b"))
            clock.return_value = 5
            self.assertEqual(cache.get("a"), 1)
            clock.return_value = 10
            self.assertIsNone(cache.get("a"))
            self.assertIsNone(cache.get("c"))
            cache.put("d", 4)
            cache.clear()
            self.assertIsNone(cache.get("d"))

    def test_concurrent_operations_keep_capacity_bounded(self):
        cache = TTLCache(max_entries=4, ttl_seconds=60)

        def use_cache(worker):
            for index in range(50):
                key = (worker, index % 8)
                cache.put(key, index)
                cache.get(key)
                if index % 11 == 0:
                    cache.clear()

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(use_cache, range(4)))
        remaining = [cache.get((worker, index)) for worker in range(4) for index in range(8)]
        self.assertLessEqual(sum(value is not None for value in remaining), 4)

    def test_disabled_cache_never_retains_values(self):
        for capacity, ttl in ((0, 10), (2, 0)):
            cache = TTLCache(capacity, ttl)
            cache.put("a", 1)
            self.assertIsNone(cache.get("a"))


class RetrievalCacheTests(unittest.IsolatedAsyncioTestCase):
    def service(self, **overrides):
        config = Settings(_env_file=None, RAG_MEASURE_RETRIEVAL_PERFORMANCE=False)
        values = config.model_dump()
        values.update(RAG_CACHE_MAX_ENTRIES=128, RAG_HYDE_CACHE_TTL_SECONDS=120,
                      RAG_EMBEDDING_CACHE_TTL_SECONDS=600,
                      RAG_HYDE_PROMPT_VERSION="hyde-v1")
        values.update(overrides)
        repository = Mock()
        repository.vector_search.return_value = []
        repository.lexical_search.return_value = []
        embedder = Mock()
        embedder.encode.return_value = [[1.0, 2.0]]
        return RetrievalService(SimpleNamespace(**values), repository, embedder, Mock())

    async def test_successful_normalized_hits_keep_lexical_original(self):
        service = self.service()
        generator = AsyncMock(return_value="Documento de BÉCAS 2026.1")
        first = await service.retrieve("  BÉCAS   2026.1 ", generator)
        second = await service.retrieve("bécas 2026.1", generator)
        self.assertEqual(first.metrics["hyde_cache"], "miss")
        self.assertEqual(first.metrics["embedding_cache"], "miss")
        self.assertEqual(second.metrics["hyde_cache"], "hit")
        self.assertEqual(second.metrics["embedding_cache"], "hit")
        generator.assert_awaited_once()
        service.embedder.encode.assert_has_calls([
            call(["  BÉCAS   2026.1 "]), call(["Documento de BÉCAS 2026.1"])
        ], any_order=True)
        self.assertEqual(service.embedder.encode.call_count, 2)
        self.assertEqual(service.repository.vector_search.call_count, 4)
        self.assertEqual(service.repository.lexical_search.call_args_list[0].args[0],
                         "  BÉCAS   2026.1 ")
        self.assertEqual(service.repository.lexical_search.call_args_list[1].args[0],
                         "bécas 2026.1")

    async def test_hyde_key_versions_models_sentences_and_meaningful_text(self):
        service = self.service()
        generator = AsyncMock(return_value="hypothesis")
        await service.retrieve("Bécas 2026.1", generator)
        for name, value in (("RAG_HYDE_PROMPT_VERSION", "hyde-v2"),
                            ("LLM_MODEL", "different-model"),
                            ("RAG_HYDE_SENTENCES", 4),
                            ("RAG_EMBEDDING_PIPELINE_VERSION", "pipeline-v2")):
            setattr(service.settings, name, value)
            await service.retrieve("Bécas 2026.1", generator)
        for question in ("Becas 2026.1", "Bécas 20261", "Bécas2026.1"):
            await service.retrieve(question, generator)
        self.assertEqual(generator.await_count, 8)

    async def test_embedding_version_and_model_invalidate(self):
        service = self.service(RAG_HYDE_ENABLED=False)
        await service.retrieve("Question")
        await service.retrieve(" question ")
        self.assertEqual(service.embedder.encode.call_count, 1)
        service.settings.RAG_EMBEDDING_PIPELINE_VERSION = "new-pipeline"
        await service.retrieve("Question")
        service.settings.RAG_EMBEDDING_MODEL = "new-model"
        await service.retrieve("Question")
        self.assertEqual(service.embedder.encode.call_count, 3)

    async def test_hyde_errors_empty_invalid_and_timeout_are_not_cached(self):
        async def slow(question):
            await asyncio.sleep(1)
            return "late"

        for generator in (AsyncMock(side_effect=RuntimeError("unavailable")),
                          AsyncMock(return_value=" "), AsyncMock(return_value=None),
                          AsyncMock(return_value={"text": "invalid"}),
                          AsyncMock(side_effect=slow)):
            with self.subTest(generator=generator):
                service = self.service(RAG_HYDE_TIMEOUT_SECONDS=0.001)
                for _ in range(2):
                    result = await service.retrieve("Original", generator)
                    self.assertFalse(result.metrics["hyde_used"])
                    self.assertEqual(result.metrics["hyde_cache"], "miss")
                self.assertEqual(generator.await_count, 2)
                service.embedder.encode.assert_called_once_with(["Original"])

    async def test_embedding_errors_are_not_cached(self):
        service = self.service(RAG_HYDE_ENABLED=False)
        service.embedder.encode.side_effect = [RuntimeError("encode failed"), [[1.0]]]
        with self.assertRaisesRegex(RuntimeError, "encode failed"):
            await service.retrieve("Original")
        result = await service.retrieve("Original")
        self.assertEqual(result.metrics["embedding_cache"], "miss")
        self.assertEqual(service.embedder.encode.call_count, 2)

    async def test_disabled_cache_preserves_original_path(self):
        service = self.service(RAG_CACHE_MAX_ENTRIES=0)
        generator = AsyncMock(return_value="hypothesis")
        for _ in range(2):
            result = await service.retrieve("Original", generator)
            self.assertEqual(result.metrics["hyde_cache"], "disabled")
            self.assertEqual(result.metrics["embedding_cache"], "disabled")
        self.assertEqual(generator.await_count, 2)
        self.assertEqual(service.embedder.encode.call_count, 4)

    async def test_cancellation_awaits_started_lexical_task(self):
        service = self.service()
        started = asyncio.Event()
        cleaned = asyncio.Event()

        async def blocked_lexical(*args):
            started.set()
            try:
                await asyncio.Future()
            finally:
                cleaned.set()

        async def pending_hyde(question):
            await started.wait()
            await asyncio.Future()

        with patch("app.rag.retrieval.asyncio.to_thread", side_effect=blocked_lexical):
            task = asyncio.create_task(service.retrieve("Original", pending_hyde))
            await asyncio.wait_for(started.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(cleaned.is_set())

    async def test_branch_failure_cancels_and_awaits_sibling(self):
        for failed_branch in ("vector", "lexical"):
            with self.subTest(failed_branch=failed_branch):
                service = self.service(RAG_HYDE_ENABLED=False)
                sibling_started = asyncio.Event()
                cleaned = asyncio.Event()

                async def run(fn, *args):
                    if fn == service.embedder.encode:
                        return [[1.0]]
                    branch = "vector" if fn == service.repository.vector_search else "lexical"
                    if branch == failed_branch:
                        await sibling_started.wait()
                        raise RuntimeError("branch failed")
                    sibling_started.set()
                    try:
                        await asyncio.Future()
                    finally:
                        cleaned.set()

                with patch("app.rag.retrieval.asyncio.to_thread", side_effect=run):
                    with self.assertRaisesRegex(RuntimeError, "branch failed"):
                        await asyncio.wait_for(service.retrieve("Original"), 1)
                self.assertTrue(cleaned.is_set())

    async def test_cancellation_awaits_both_search_branches(self):
        service = self.service(RAG_HYDE_ENABLED=False)
        started = {branch: asyncio.Event() for branch in ("vector", "lexical")}
        cleaned = set()

        async def run(fn, *args):
            if fn == service.embedder.encode:
                return [[1.0]]
            branch = "vector" if fn == service.repository.vector_search else "lexical"
            started[branch].set()
            try:
                await asyncio.Future()
            finally:
                cleaned.add(branch)

        with patch("app.rag.retrieval.asyncio.to_thread", side_effect=run):
            task = asyncio.create_task(service.retrieve("Original"))
            await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(cleaned, {"vector", "lexical"})
