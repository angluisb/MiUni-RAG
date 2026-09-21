from fastapi import APIRouter
from app.core.config import Config
from app.schemas.chat import QueryRequest, QueryResponse
from app.services.llm_service import get_chat_response
chatbot_router = APIRouter()

@chatbot_router.post("/chat")
async def chat_endpoint(request:QueryRequest ) -> QueryResponse:
    generated_answer = await get_chat_response(request.question)
    return {
        "query":request.question,
        "answer": generated_answer
        }