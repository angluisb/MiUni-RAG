from fastapi import FastAPI
from app.api.v1.endpoints.chat import chatbot_router
version = "v1"

app = FastAPI(
    title="Chatbot MiUni",
    version=version
    )

app.include_router(chatbot_router, prefix=f"/api/{version}/chat", tags=["chat"])

