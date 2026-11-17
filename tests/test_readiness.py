import unittest
from contextlib import ExitStack
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

import app as application


class ReadinessTests(unittest.TestCase):
    def client(self, *, enabled=True, warmup=True, warmup_error=None, db_error=None):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(application.Config, "RAG_ENABLED", enabled))
        stack.enter_context(patch.object(application.Config, "RAG_WARMUP_ON_STARTUP", warmup))
        self.warmup = stack.enter_context(patch.object(
            application, "warmup_retriever", new=AsyncMock(side_effect=warmup_error)))
        self.retriever = Mock()
        self.retriever.repository.check.side_effect = db_error
        stack.enter_context(patch(
            "app.services.readiness._get_retriever", return_value=self.retriever))
        self.chat = stack.enter_context(patch(
            "app.api.v1.endpoints.chat.get_chat_response", new=AsyncMock(return_value="answer")))
        return stack.enter_context(TestClient(application.app))

    def test_successful_startup_warms_model_and_reports_both_dependencies(self):
        client = self.client()
        self.warmup.assert_awaited_once()
        self.retriever.repository.check.assert_called_once()
        response = client.get("/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "ready", "model": "ready", "postgresql": "ready"})
        self.assertEqual(client.post("/api/v1/chat", json={"question": "hello"}).status_code, 200)

    def test_warmup_failure_keeps_liveness_but_blocks_normal_chat_without_secrets(self):
        client = self.client(warmup_error=RuntimeError("password=secret"))
        self.assertEqual(client.get("/health/live").json(), {"status": "alive"})
        response = client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {
            "status": "not_ready", "model": "failed", "postgresql": "ready"})
        for path in ("/api/v1/chat", "/api/v1/chat/stream"):
            response = client.post(path, json={"question": "hello"})
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("secret", response.text)
        self.chat.assert_not_awaited()

    def test_database_failure_is_independent_and_recovers_on_health_check(self):
        client = self.client(db_error=RuntimeError("postgres://user:secret@host"))
        response = client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {
            "status": "not_ready", "model": "ready", "postgresql": "failed"})
        self.assertEqual(client.post("/api/v1/chat", json={"question": "hello"}).status_code, 503)
        self.retriever.repository.check.side_effect = None
        self.assertEqual(client.get("/health/ready").status_code, 200)
        self.assertEqual(client.post("/api/v1/chat", json={"question": "hello"}).status_code, 200)
        self.retriever.repository.check.side_effect = RuntimeError("lost connection")
        self.assertEqual(client.get("/health/ready").status_code, 503)
        self.assertEqual(client.get("/health/live").status_code, 200)

    def test_explicit_warmup_optout_preserves_chat_without_claiming_readiness(self):
        client = self.client(warmup=False)
        response = client.get("/health/ready")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {
            "status": "not_ready", "model": "not_warmed", "postgresql": "not_checked"})
        self.retriever.repository.check.assert_not_called()
        self.warmup.assert_not_awaited()
        self.assertEqual(client.post("/api/v1/chat", json={"question": "hello"}).status_code, 200)

    def test_disabled_rag_has_no_required_dependencies(self):
        client = self.client(enabled=False)
        response = client.get("/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "ready", "model": "disabled", "postgresql": "disabled"})
        self.warmup.assert_not_awaited()
        self.retriever.repository.check.assert_not_called()
        self.assertEqual(client.post("/api/v1/chat", json={"question": "hello"}).status_code, 200)
