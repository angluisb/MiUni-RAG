"""Independent S3/S4/S5 probes; no network or database dependencies."""
import asyncio
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.core.config import Settings
from app.rag.retrieval import RetrievalService
from app.services import llm_service


class IndependentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_lexical_starts_before_hyde_completes(self):
        started = threading.Event()

        class Repository:
            def lexical_search(self, *args):
                started.set()
                return []

            def vector_search(self, *args):
                return []

        class Embedder:
            def encode(self, texts):
                return ["vector"]

        async def hyde(question):
            self.assertTrue(await asyncio.to_thread(started.wait, 1))
            return "passage"

        settings = Settings(_env_file=None, RAG_MEASURE_RETRIEVAL_PERFORMANCE=False)
        await RetrievalService(settings, Repository(), Embedder()).retrieve("Becas", hyde)

    async def test_catalog_error_is_not_cached(self):
        class Repository:
            attempts = 0

            def list_campus_places(self):
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("catalog temporarily unavailable")
                return [{"id": "safe", "nombre": "Biblioteca Central", "map_url": "/mapa?lugar=safe"}]

        repository = Repository()
        llm_service._get_catalog_cache.cache_clear()
        self.addCleanup(llm_service._get_catalog_cache.cache_clear)
        with patch.object(llm_service.Config, "RAG_ENABLED", True), \
             patch.object(llm_service, "_get_retriever", return_value=SimpleNamespace(repository=repository)), \
             patch.object(llm_service, "_get_llm", side_effect=AssertionError("must bypass model")):
            with self.assertRaises(RuntimeError):
                await llm_service.get_chat_response("donde esta Biblioteca Central")
            answer = await llm_service.get_chat_response("donde esta Biblioteca Central")
        self.assertIn("/mapa?lugar=safe", answer)
        self.assertEqual(repository.attempts, 2)


if __name__ == "__main__":
    unittest.main()
