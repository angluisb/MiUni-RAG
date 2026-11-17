from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    API_KEY: str = ""
    LLM_MODEL: str = "gemini-3.1-flash-lite"
    LLM_MAX_OUTPUT_TOKENS: int = Field(default=1024, ge=128, le=8192)
    LLM_GENERATION_TIMEOUT_SECONDS: float = Field(default=30, gt=0, le=180)
    LLM_THINKING_LEVEL: Literal["minimal", "low", "medium", "high"] = "minimal"
    CHAT_MAX_CONCURRENT_REQUESTS: int = Field(default=4, ge=1, le=32)
    CHAT_QUEUE_TIMEOUT_SECONDS: float = Field(default=2, gt=0, le=30)
    RAG_CACHE_MAX_ENTRIES: int = Field(default=128, ge=0, le=4096)
    RAG_HYDE_CACHE_TTL_SECONDS: float = Field(default=120, ge=0)
    RAG_EMBEDDING_CACHE_TTL_SECONDS: float = Field(default=600, ge=0)
    RAG_CATALOG_CACHE_TTL_SECONDS: float = Field(default=15, ge=0)
    RAG_HYDE_PROMPT_VERSION: str = "hyde-v1"
    RAG_TEMPORAL_FILTER_ENABLED: bool = False
    DATABASE_URL: str = ""
    RAG_ENABLED: bool = False
    RAG_EMBEDDING_MODEL: Literal["BAAI/bge-m3"] = "BAAI/bge-m3"
    RAG_EMBEDDING_DIMENSION: Literal[1024] = 1024
    RAG_EMBEDDING_BATCH_SIZE: int = Field(default=8, ge=1, le=128)
    RAG_MODEL_DEVICE: str = "cpu"
    RAG_MODEL_CACHE: str = str(ROOT / ".cache" / "huggingface")
    RAG_WARMUP_ON_STARTUP: bool = True
    RAG_EMBEDDING_PIPELINE_VERSION: str = "rag-embeddings-v1"
    RAG_HYBRID_SEARCH_ENABLED: bool = True
    RAG_HYDE_ENABLED: bool = True
    RAG_HYDE_SENTENCES: int = Field(default=3, ge=2, le=4)
    RAG_HYDE_TIMEOUT_SECONDS: float = Field(default=3, gt=0)
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
    RAG_DB_POOL_ENABLED: bool = True
    RAG_DB_POOL_MAX_SIZE: int = Field(default=4, ge=1, le=32)
    RAG_DB_POOL_MAX_WAITING: int = Field(default=16, ge=1, le=256)
    RAG_DB_POOL_TIMEOUT_SECONDS: float = Field(default=5, gt=0)

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra= "ignore"
    )
Config = Settings()
