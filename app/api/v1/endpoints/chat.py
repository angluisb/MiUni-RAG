from fastapi import HTTPException, APIRouter
from app.core.config import Config
from langchain_google_genai import ChatGoogleGenerativeAI

chatbot_router = APIRouter()
llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash", api_key=Config.API_KEY)


@chatbot_router.post("/chat")
async def chat_endpoint():
    response = await llm.ainvoke("Hola, ¿cómo estás?")
    return {"message": response.content}