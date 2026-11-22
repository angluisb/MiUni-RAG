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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", help="JSONL completos; por defecto HTML y PDF existentes")
    parser.add_argument("--dry-run", action="store_true", help="Validar JSONL sin base ni descargar el modelo")
    parser.add_argument("--check-db", action="store_true", help="Comprobar extension, esquema, indices y conteos")
    parser.add_argument("--limit-documents", type=int, help="Limitar por documentos completos para una prueba")
    parser.add_argument("--temporal-manifest", type=Path, help="Reviewed source temporal metadata JSON")
    parser.add_argument("--version-archive-dir", type=Path,
                        help="Archive full old rows outside Git before refresh (absolute directory)")
    parser.add_argument("--refresh-guard", type=Path,
                        help="Version 1 JSON sources with expected source_url, source_id and temporal_status; requires archive")
    args = parser.parse_args(argv)
    if (args.version_archive_dir is None) != (args.refresh_guard is None):
        parser.error("--version-archive-dir and --refresh-guard must be used together")
    if args.check_db and args.version_archive_dir is not None:
        parser.error("--check-db cannot be combined with refresh options")
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
    documents = load_documents(paths, temporal_manifest=args.temporal_manifest)
    if not documents:
        parser.error("Los JSONL no contienen chunks")
    selected = list(documents.values())[:args.limit_documents]
    guards = {}
    planned_archive = {}
    if args.version_archive_dir is not None:
        from app.rag.version_archive import load_refresh_guard, validate_archive_directory
        args.version_archive_dir = validate_archive_directory(args.version_archive_dir)
        guards = load_refresh_guard(args.refresh_guard, [chunks[0].source_url for chunks in selected])
        planned_archive = {"planned_version_archive_dir": str(args.version_archive_dir)}
    print(json.dumps({"documents": len(selected), "chunks": sum(map(len, selected)),
                      "dry_run": args.dry_run, **planned_archive}), flush=True)
    if args.dry_run:
        return 0
    print(json.dumps(repository.check()), flush=True)
    indexer = ChunkIndexer(Config, repository, DenseEmbedder(Config))
    totals = {"chunks": 0, "embedded": 0, "reused": 0, "deleted_stale": 0}
    for index, chunks in enumerate(selected, 1):
        started = perf_counter()
        options = {}
        if args.version_archive_dir is not None:
            guard = guards[chunks[0].source_url]
            options = {"archive_directory": args.version_archive_dir,
                       "expected_source_id": guard["source_id"],
                       "expected_temporal_status": guard["temporal_status"]}
        stats = indexer.index_document(chunks, **options)
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
