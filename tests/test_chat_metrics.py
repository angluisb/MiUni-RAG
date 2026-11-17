import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi.testclient import TestClient

from app import app
from app.services import llm_service
from scripts import benchmark_chat


class BenchmarkSummaryTests(unittest.TestCase):
    def test_percentiles_exclude_failures_and_expose_sample_counts(self):
        runs = [{"ok": True, "total_ms": n, "first_text_ms": n / 2}
                for n in range(1, 21)] + [{"ok": False, "elapsed_ms": 9999}]
        summary = benchmark_chat.summarize(runs)
        self.assertEqual(summary["successful_runs"], 20)
        self.assertEqual(summary["failed_runs"], 1)
        self.assertEqual(summary["total_ms"],
                         {"samples": 20, "p50": 10, "p95": 19, "p99": 20})
        self.assertEqual(benchmark_chat.summarize([])["total_ms"],
                         {"samples": 0, "p50": None, "p95": None, "p99": None})


class ChatMetricsTests(unittest.TestCase):
    def test_real_service_stages_and_warm_classification_are_separate(self):
        retriever = Mock()
        retriever.embedder._model = object()
        retriever.repository.list_campus_places.return_value = []
        retriever.retrieve = AsyncMock(return_value=SimpleNamespace(
            chunks=[], metrics={"embedding_ms": 2, "hyde_ms": 3, "total_retrieval_ms": 5}))

        async def chunks(messages):
            yield SimpleNamespace(content="")
            yield SimpleNamespace(content="answer")

        model = Mock()
        model.astream.side_effect = chunks
        with patch.object(llm_service.Config, "RAG_ENABLED", True), \
             patch("app.warmup_retriever", new_callable=AsyncMock, create=True), \
             patch.object(llm_service.Config, "RAG_WARMUP_ON_STARTUP", False), \
             patch.object(llm_service, "_get_retriever", return_value=retriever), \
             patch.object(llm_service, "_get_llm", return_value=model), \
             self.assertLogs("uvicorn.error.chat_metrics", level="INFO") as logs:
            with TestClient(app) as client:
                response = client.post("/api/v1/chat/stream", json={"question": "Becas"})
        self.assertEqual(response.text, "answer")
        record = json.loads(logs.output[-1].split("chat_request ", 1)[1])
        self.assertEqual(record["model_state"], "warm")
        self.assertEqual(record["stages_ms"]["embedding_ms"], 2)
        for stage in ("catalog_ms", "prompt_build_ms", "generation_first_token_ms",
                      "generation_complete_ms", "http_ms"):
            self.assertGreaterEqual(record["stages_ms"][stage], 0)
        self.assertLessEqual(record["stages_ms"]["generation_first_token_ms"],
                             record["stages_ms"]["generation_complete_ms"])

    def test_errors_keep_502_contract_and_have_separate_outcome_windows(self):
        async def fail(question):
            raise RuntimeError("private provider details")
            yield "unreachable"

        with patch("app.api.v1.endpoints.chat.stream_chat_response", fail), \
             patch("app.warmup_retriever", new_callable=AsyncMock, create=True), \
             patch.object(llm_service.Config, "RAG_WARMUP_ON_STARTUP", False), \
             self.assertLogs("uvicorn.error.chat_metrics", level="INFO") as logs:
            with TestClient(app) as client:
                response = client.post("/api/v1/chat/stream", json={"question": "Becas"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json(), {"detail": "No se pudo obtener respuesta del modelo."})
        record = json.loads(logs.output[-1].split("chat_request ", 1)[1])
        self.assertEqual(record["outcome"], "error")
        self.assertNotIn("private provider details", logs.output[-1])

    def test_stream_and_json_keep_contract_and_log_http_completion_without_content(self):
        async def stream(question):
            yield "Respuesta "
            yield "completa"

        async def answer(question):
            return "Respuesta completa"

        with patch("app.api.v1.endpoints.chat.stream_chat_response", stream), \
             patch("app.api.v1.endpoints.chat.get_chat_response", answer), \
             patch("app.warmup_retriever", new_callable=AsyncMock, create=True), \
             patch.object(llm_service.Config, "RAG_WARMUP_ON_STARTUP", False), \
             self.assertLogs("uvicorn.error.chat_metrics", level="INFO") as logs:
            with TestClient(app) as client:
                for path in ("/api/v1/chat", "/api/v1/chat/stream"):
                    response = client.post(path, json={"question": "private question"})
                    self.assertEqual(response.status_code, 200)
                    if path.endswith("stream"):
                        self.assertEqual(response.text, "Respuesta completa")
                    else:
                        self.assertEqual(response.json(),
                                         {"query": "private question", "answer": "Respuesta completa"})
        records = [json.loads(line.split("chat_request ", 1)[1]) for line in logs.output]
        self.assertEqual(len(records), 2)
        self.assertNotEqual(records[0]["request_id"], records[1]["request_id"])
        for record in records:
            self.assertEqual(record["status"], 200)
            self.assertGreaterEqual(record["stages_ms"]["http_ms"], 0)
            self.assertEqual(record["cache"], "disabled")
        self.assertNotIn("private question", " ".join(logs.output))
        self.assertNotIn("Respuesta completa", " ".join(logs.output))

    def test_stage_percentiles_are_bounded_and_cold_warm_are_not_mixed(self):
        from app.services.chat_metrics import StageWindow

        window = StageWindow(max_samples=2)
        for value in (999, 10, 20):
            window.observe("embedding_ms", "warm", "disabled", "ok", value)
        window.observe("embedding_ms", "cold", "disabled", "ok", 500)
        self.assertEqual(window.observe("embedding_ms", "warm", "disabled", "ok", 30),
                         {"samples": 2, "p50": 20, "p95": 30, "p99": 30})


if __name__ == "__main__":
    unittest.main()
