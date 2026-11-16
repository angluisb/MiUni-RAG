from fastapi import FastAPI
from app.api.v1.endpoints.chat import chatbot_router
from app.services.chat_metrics import ChatMetricsMiddleware
version = "v1"

app = FastAPI(
    title="Chatbot MiUni",
    version=version
    )

app.include_router(chatbot_router, prefix=f"/api/{version}", tags=["chat"])


app.add_middleware(ChatMetricsMiddleware)
