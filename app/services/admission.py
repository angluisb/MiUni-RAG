"""Keep bounded chat capacity for the entire HTTP response, including streaming."""
import asyncio

from fastapi.responses import JSONResponse


class ChatAdmissionMiddleware:
    def __init__(self, app, queue_timeout=2):
        self.app = app
        self.queue_timeout = queue_timeout

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") not in (
                "/api/v1/chat", "/api/v1/chat/stream"):
            return await self.app(scope, receive, send)
        slots = getattr(scope["app"].state, "chat_slots", None)
        if slots is None:
            return await self.app(scope, receive, send)
        try:
            await asyncio.wait_for(slots.acquire(), self.queue_timeout)
        except TimeoutError:
            response = JSONResponse(status_code=503, content={
                "detail": "Chat capacity is busy. Retry shortly."}, headers={"Retry-After": "2"})
            return await response(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            slots.release()
