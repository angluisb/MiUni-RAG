from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class InputChunk(BaseModel):
    id: str = Field(min_length=1)
    source_type: Literal["html", "pdf"]
    source_url: str = Field(min_length=1)
    document_title: str = Field(min_length=1)
    category: str | None = None
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content", "source_url", "document_title", "id")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El campo no puede estar vacio")
        return value


@dataclass
class SearchHit:
    id: str
    source_url: str
    document_title: str
    content: str
    metadata: dict[str, Any]
    score: float


@dataclass
class RetrievalResult:
    chunks: list[SearchHit]
    metrics: dict[str, Any]
