import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from app import app
from app.services import llm_service


class GenerationBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_generation_timeout_cancels_provider_and_returns_actionable_error(self):
        cancelled = asyncio.Event()

        async def slow(messages):
            try:
                await asyncio.sleep(1)
            finally:
                cancelled.set()

        model = Mock(ainvoke=AsyncMock(side_effect=slow))
        with patch.object(llm_service.Config, "RAG_ENABLED", False), \
             patch.object(llm_service.Config, "LLM_GENERATION_TIMEOUT_SECONDS", 0.01, create=True), \
             patch.object(llm_service, "_get_llm", return_value=model):
            with self.assertRaises(TimeoutError):
                await llm_service.get_chat_response("Becas")
        self.assertTrue(cancelled.is_set())

    async def test_stream_is_progressive_and_closes_provider_on_timeout(self):
        closed = asyncio.Event()

        async def slow_stream(messages):
            try:
                yield SimpleNamespace(content="first")
                await asyncio.sleep(1)
                yield SimpleNamespace(content="last")
            finally:
                closed.set()

        model = Mock(astream=Mock(side_effect=slow_stream))
        with patch.object(llm_service.Config, "RAG_ENABLED", False), \
             patch.object(llm_service.Config, "LLM_GENERATION_TIMEOUT_SECONDS", 0.01, create=True), \
             patch.object(llm_service, "_get_llm", return_value=model):
            stream = llm_service.stream_chat_response("Becas")
            self.assertEqual(await anext(stream), "first")
            with self.assertRaises(TimeoutError):
                await anext(stream)
            await stream.aclose()
        self.assertTrue(closed.is_set())

    async def test_catalog_and_retrieval_overlap_without_changing_prompt_sources(self):
        import threading
        catalog_started = threading.Event()
        retrieval_started = threading.Event()

        def places():
            catalog_started.set()
            if not retrieval_started.wait(0.2):
                raise AssertionError("retrieval did not start while catalog was pending")
            return []

        async def retrieve(question, hyde):
            retrieval_started.set()
            self.assertTrue(await asyncio.to_thread(catalog_started.wait, 0.2))
            return SimpleNamespace(chunks=[], metrics={})

        retriever = Mock()
        retriever.repository.list_campus_places.side_effect = places
        retriever.retrieve = AsyncMock(side_effect=retrieve)
        with patch.object(llm_service.Config, "RAG_ENABLED", True), \
             patch.object(llm_service, "_get_retriever", return_value=retriever):
            messages = await llm_service._build_messages("Becas")
        self.assertEqual(messages[-1].content, "Becas")
        self.assertIn("Fuentes recuperadas", messages[-2].content)


class GenerationConfigTests(unittest.TestCase):
    def test_model_has_explicit_output_thinking_and_transport_limits(self):
        llm_service._get_llm.cache_clear()
        try:
            with patch.object(llm_service.Config, "API_KEY", "test-key"), \
                 patch.object(llm_service.Config, "LLM_MODEL", "gemini-3.1-flash-lite"), \
                 patch.object(llm_service, "ChatGoogleGenerativeAI") as constructor:
                llm_service._get_llm()
            options = constructor.call_args.kwargs
            self.assertGreater(options["max_output_tokens"], 0)
            self.assertEqual(options["thinking_config"], {"thinking_level": "minimal"})
            self.assertGreater(options["timeout"], 0)
            self.assertEqual(options["max_retries"], 0)
        finally:
            llm_service._get_llm.cache_clear()

    def test_timeout_is_504_before_stream_headers_for_both_routes(self):
        async def timeout(question):
            raise TimeoutError()

        async def stream_timeout(question):
            raise TimeoutError()
            yield "unreachable"

        with patch.object(llm_service.Config, "RAG_WARMUP_ON_STARTUP", False), \
             patch("app.api.v1.endpoints.chat.get_chat_response", timeout), \
             patch("app.api.v1.endpoints.chat.stream_chat_response", stream_timeout):
            with TestClient(app) as client:
                for path in ("/api/v1/chat", "/api/v1/chat/stream"):
                    response = client.post(path, json={"question": "Becas"})
                    self.assertEqual(response.status_code, 504)
                    self.assertIn("intenta", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
