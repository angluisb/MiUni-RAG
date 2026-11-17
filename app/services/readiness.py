"""Dependency readiness without leaking connection details or startup exceptions."""

import asyncio

from app.services.llm_service import _get_retriever


class Readiness:
    def __init__(self, settings):
        self.enabled = settings.RAG_ENABLED
        self.required = self.enabled and settings.RAG_WARMUP_ON_STARTUP
        self.model = "not_warmed" if self.enabled else "disabled"
        self.postgresql = "not_checked" if self.enabled else "disabled"

    @property
    def ready(self):
        return not self.enabled or (self.model == "ready" and self.postgresql == "ready")

    @property
    def blocks_chat(self):
        return self.required and not self.ready

    async def initialize(self, warmup):
        if not self.required:
            return
        try:
            await warmup()
            self.model = "ready"
        except Exception:
            self.model = "failed"
        await self.check_database()

    async def check_database(self):
        if not self.required:
            return
        try:
            # Both construction and the synchronous check stay off the event loop.
            await asyncio.to_thread(lambda: _get_retriever().repository.check())
            self.postgresql = "ready"
        except Exception:
            self.postgresql = "failed"

    def snapshot(self):
        return {
            "status": "ready" if self.ready else "not_ready",
            "model": self.model,
            "postgresql": self.postgresql,
        }
