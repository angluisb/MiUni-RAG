"""Inspect vector, lexical or hybrid retrieval without generating a final answer."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Config
from app.rag.repository import RagRepository
from app.rag.retrieval import RetrievalService


async def run(args):
    settings = Config.model_copy(update={
        "RAG_HYBRID_SEARCH_ENABLED": args.mode == "hybrid",
        "RAG_HYDE_ENABLED": args.hyde,
    })
    repository = RagRepository(settings)
    if args.mode == "lexical":
        hits = await asyncio.to_thread(repository.lexical_search, args.question, settings.RAG_CONTEXT_TOP_K)
        return {"chunks": [asdict(hit) for hit in hits]}
    from app.services.llm_service import generate_hyde

    result = await RetrievalService(settings).retrieve(args.question, generate_hyde if args.hyde else None)
    return asdict(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    parser.add_argument("--mode", choices=["hybrid", "vector", "lexical"], default="hybrid")
    parser.add_argument("--hyde", action="store_true", help="Usar el LLM para HyDE; requiere API_KEY")
    args = parser.parse_args()
    if not args.question.strip():
        parser.error("La pregunta no puede estar vacia")
    if args.hyde and args.mode == "lexical":
        parser.error("HyDE solo aplica a la rama vectorial")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(json.dumps(asyncio.run(run(args)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
