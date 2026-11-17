import asyncio
from types import SimpleNamespace
import unittest


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_limit_rejects_queued_request_and_releases_on_cancellation(self):
        from app.services.admission import ChatAdmissionMiddleware

        slots = asyncio.Semaphore(1)
        started = asyncio.Event()

        async def downstream(scope, receive, send):
            started.set()
            await asyncio.Event().wait()

        async def receive():
            return {"type": "http.disconnect"}

        messages = []

        async def send(message):
            messages.append(message)

        middleware = ChatAdmissionMiddleware(downstream, queue_timeout=0.01)
        scope = {"type": "http", "path": "/api/v1/chat/stream",
                 "app": SimpleNamespace(state=SimpleNamespace(chat_slots=slots))}
        first = asyncio.create_task(middleware(scope, receive, send))
        await started.wait()
        await middleware(scope, receive, send)
        self.assertEqual(messages[0]["status"], 503)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        await asyncio.wait_for(slots.acquire(), 0.05)
        slots.release()


if __name__ == "__main__":
    unittest.main()
