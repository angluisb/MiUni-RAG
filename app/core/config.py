from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    API_KEY: str = ""
    LLM_MODEL: str = "gemini-3.1-flash-lite"
    DATABASE_URL: str = ""
    RAG_ENABLED: bool = False
    RAG_EMBEDDING_MODEL: Literal["BAAI/bge-m3"] = "BAAI/bge-m3"
    RAG_EMBEDDING_DIMENSION: Literal[1024] = 1024
    RAG_EMBEDDING_BATCH_SIZE: int = Field(default=8, ge=1, le=128)
    RAG_MODEL_DEVICE: str = "cpu"
    RAG_MODEL_CACHE: str = str(ROOT / ".cache" / "huggingface")
    RAG_EMBEDDING_PIPELINE_VERSION: str = "rag-embeddings-v1"
    RAG_HYBRID_SEARCH_ENABLED: bool = True
    RAG_HYDE_ENABLED: bool = True
    RAG_HYDE_SENTENCES: int = Field(default=3, ge=2, le=4)
    RAG_HYDE_TIMEOUT_SECONDS: float = Field(default=15, gt=0)
    RAG_VECTOR_TOP_N: int = Field(default=30, ge=1, le=500)
    RAG_LEXICAL_TOP_N: int = Field(default=30, ge=1, le=500)
    RAG_RRF_K: int = Field(default=60, ge=1)
    RAG_CONTEXT_TOP_K: int = Field(default=8, ge=1, le=100)
    RAG_RERANK_ENABLED: bool = False
    RAG_RERANK_PROVIDER: Literal["local_bge"] = "local_bge"
    RAG_RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RAG_MEASURE_RETRIEVAL_PERFORMANCE: bool = True
    RAG_EXPERIMENT_NAME: str = "hyde_hybrid_v1"
    RAG_LOG_RETRIEVAL_RESULTS: bool = False
    RAG_LOG_CONTEXT_CHUNKS: bool = False
    RAG_DB_CONNECT_TIMEOUT_SECONDS: int = Field(default=5, ge=1)
    RAG_DB_STATEMENT_TIMEOUT_MS: int = Field(default=30000, ge=1)

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra= "ignore"
    )
Config = Settings()
