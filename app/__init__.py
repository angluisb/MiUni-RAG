from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from app.api.v1.endpoints.chat import chatbot_router
from app.core.config import Config
from app.services.llm_service import warmup_retriever, close_retriever
from app.services.chat_metrics import ChatMetricsMiddleware
from app.services.readiness import Readiness
version = "v1"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _app.state.readiness = Readiness(Config)
    await _app.state.readiness.initialize(warmup_retriever)
    try:
        yield
    finally:
        await close_retriever()


app = FastAPI(
    title="Chatbot MiUni",
    version=version,
    lifespan=lifespan,
    )

app.include_router(chatbot_router, prefix=f"/api/{version}", tags=["chat"])
app.state.readiness = Readiness(Config)


@app.middleware("http")
async def require_warmup(request, call_next):
    if (request.url.path in (f"/api/{version}/chat", f"/api/{version}/chat/stream")
            and app.state.readiness.blocks_chat):
        return JSONResponse(status_code=503, content={"detail": "RAG dependencies are not ready."})
    return await call_next(request)


@app.get("/health/live", tags=["health"])
async def liveness():
    return {"status": "alive"}


@app.get("/health/ready", tags=["health"])
async def readiness():
    state = app.state.readiness
    await state.check_database()
    return JSONResponse(status_code=200 if state.ready else 503, content=state.snapshot())


# Observe rejected requests too, before the readiness gate returns a response.
app.add_middleware(ChatMetricsMiddleware)
