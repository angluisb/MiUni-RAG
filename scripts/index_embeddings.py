"""Index complete HTML/PDF documents into MiUni.Api's rag_chunk table."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Config
from app.rag.embeddings import DenseEmbedder
from app.rag.indexing import ChunkIndexer, load_documents
from app.rag.repository import RagRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", help="JSONL completos; por defecto HTML y PDF existentes")
    parser.add_argument("--dry-run", action="store_true", help="Validar JSONL sin base ni descargar el modelo")
    parser.add_argument("--check-db", action="store_true", help="Comprobar extension, esquema, indices y conteos")
    parser.add_argument("--limit-documents", type=int, help="Limitar por documentos completos para una prueba")
    args = parser.parse_args()
    if args.limit_documents is not None and args.limit_documents < 1:
        parser.error("--limit-documents debe ser positivo")
    repository = RagRepository(Config)
    if args.check_db:
        print(json.dumps(repository.check(), indent=2))
        return 0
    paths = args.input if args.input is not None else [
        path for path in (ROOT / "data/processed/chunks/html_chunks.jsonl",
                          ROOT / "data/processed/chunks/pdf_chunks.jsonl") if path.exists()]
    if not paths:
        parser.error("No hay JSONL. Ejecuta ingest_html.py / ingest_pdf.py primero")
    documents = load_documents(paths)
    if not documents:
        parser.error("Los JSONL no contienen chunks")
    selected = list(documents.values())[:args.limit_documents]
    print(json.dumps({"documents": len(selected), "chunks": sum(map(len, selected)),
                      "dry_run": args.dry_run}), flush=True)
    if args.dry_run:
        return 0
    print(json.dumps(repository.check()), flush=True)
    indexer = ChunkIndexer(Config, repository, DenseEmbedder(Config))
    totals = {"chunks": 0, "embedded": 0, "reused": 0, "deleted_stale": 0}
    for index, chunks in enumerate(selected, 1):
        started = perf_counter()
        stats = indexer.index_document(chunks)
        for key, value in stats.items():
            totals[key] += value
        print(json.dumps({"document": index, "source_url": chunks[0].source_url,
                          "elapsed_ms": round((perf_counter() - started) * 1000, 1), **stats}), flush=True)
    print(json.dumps({"total": totals}), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
