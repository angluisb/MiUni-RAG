"""Bounded, process-local chat latency windows; never retain question or answer text."""
from collections import defaultdict, deque
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import logging
from math import ceil
from threading import Lock
from time import perf_counter
from uuid import uuid4


def percentiles(values):
    ordered = sorted(values)
    return {"samples": len(ordered), **{
        f"p{p}": ordered[ceil(len(ordered) * p / 100) - 1] if ordered else None
        for p in (50, 95, 99)
    }}


class StageWindow:
    def __init__(self, max_samples=1024):
        self._windows = defaultdict(lambda: deque(maxlen=max_samples))
        self._lock = Lock()

    def observe(self, stage, model_state, cache, outcome, duration):
        with self._lock:
            values = self._windows[stage, model_state, cache, outcome]
            values.append(round(duration, 3))
            return percentiles(values)


@dataclass
class RequestTrace:
    model_state: str = "not_used"
    cache: str = "disabled"
    stages: dict = field(default_factory=dict)


current_trace = ContextVar("chat_trace", default=None)
windows = StageWindow()
logger = logging.getLogger("uvicorn.error.chat_metrics")


def record_stage(name, milliseconds):
    trace = current_trace.get()
    if trace is not None:
        trace.stages[name] = trace.stages.get(name, 0) + milliseconds


def record_retrieval(metrics, model_state):
    trace = current_trace.get()
    if trace is not None:
        trace.model_state = model_state
        for key in ("hyde_ms", "embedding_ms", "vector_search_ms", "lexical_search_ms",
                    "rrf_ms", "rerank_ms", "total_retrieval_ms"):
            if key in metrics:
                record_stage(key, metrics[key])


class ChatMetricsMiddleware:
    """Measure the entire ASGI response, including stream completion/disconnect."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") not in (
                "/api/v1/chat", "/api/v1/chat/stream"):
            return await self.app(scope, receive, send)
        trace = RequestTrace()
        token = current_trace.set(trace)
        started = perf_counter()
        status, completed = 500, False

        async def measured_send(message):
            nonlocal status, completed
            await send(message)
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True

        try:
            await self.app(scope, receive, measured_send)
        finally:
            record_stage("http_ms", (perf_counter() - started) * 1000)
            outcome = "ok" if completed and status < 400 else "error" if completed else "interrupted"
            aggregates = {name: windows.observe(name, trace.model_state, trace.cache, outcome, duration)
                          for name, duration in trace.stages.items()}
            current_trace.reset(token)
            logger.info("chat_request %s", json.dumps({
                "request_id": str(uuid4()), "path": scope["path"], "status": status,
                "outcome": outcome, "model_state": trace.model_state, "cache": trace.cache,
                "stages_ms": trace.stages, "window": aggregates,
            }))
