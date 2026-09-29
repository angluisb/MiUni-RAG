from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.schemas.chat import QueryRequest, QueryResponse
from app.services.llm_service import get_chat_response, stream_chat_response
chatbot_router = APIRouter()

def _normalize_question(question: str) -> str:
    normalized = question.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="La pregunta no puede estar vacia.")
    return normalized

@chatbot_router.post("/chat")
async def chat_endpoint(request: QueryRequest) -> QueryResponse:
    question = _normalize_question(request.question)
    try:
        generated_answer = await get_chat_response(question)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="No se pudo obtener respuesta del modelo."
        ) from exc

    if not generated_answer.strip():
        raise HTTPException(status_code=502, detail="El modelo devolvio una respuesta vacia.")

    return {
        "query": question,
        "answer": generated_answer
        }

@chatbot_router.post("/chat/stream")
async def chat_stream_endpoint(request: QueryRequest) -> StreamingResponse:
    question = _normalize_question(request.question)

    async def generate():
        async for chunk in stream_chat_response(question):
            yield chunk

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")
