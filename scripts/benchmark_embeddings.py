"""Estimate pending embedding time from a small local sample; never writes to PostgreSQL."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.config import Config
from app.rag.embeddings import DenseEmbedder
from app.rag.indexing import load_documents
from app.rag.models import text_hash
from app.rag.repository import RagRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-per-bucket", type=int, default=2)
    parser.add_argument("--output", type=Path, default=ROOT / ".cache/rag-benchmark.json")
    args = parser.parse_args()
    if args.samples_per_bucket < 1:
        parser.error("--samples-per-bucket debe ser positivo")
    paths = [path for path in (ROOT / "data/processed/chunks/html_chunks.jsonl",
                              ROOT / "data/processed/chunks/pdf_chunks.jsonl") if path.exists()]
    if not paths:
        parser.error("No se encontraron JSONL")
    documents = load_documents(paths)
    if not documents:
        parser.error("Los JSONL no contienen chunks")
    texts = {text_hash(chunk.content): chunk.content
             for chunks in documents.values() for chunk in chunks}
    repository = RagRepository(Config)
    with repository.connect() as conn:
        cached = conn.execute(
            """SELECT DISTINCT content_sha256 FROM rag_chunk
               WHERE embedding IS NOT NULL AND embedded_at IS NOT NULL
                 AND embedding_model = %s AND embedding_dimension = %s
                 AND metadata->>'embedding_pipeline_version' = %s
                 AND metadata->>'embedding_input_sha256' = content_sha256""",
            (Config.RAG_EMBEDDING_MODEL, Config.RAG_EMBEDDING_DIMENSION,
             Config.RAG_EMBEDDING_PIPELINE_VERSION),
        ).fetchall()
    cached_hashes = {row["content_sha256"] for row in cached}
    pending = [text for digest, text in texts.items() if digest not in cached_hashes]
    report = {"measured_at": datetime.now(timezone.utc).isoformat(),
              "documents": len(documents), "chunks": sum(map(len, documents.values())),
              "unique_contents": len(texts), "pending_unique_contents": len(pending),
              "device": Config.RAG_MODEL_DEVICE,
              "configured_batch_size": Config.RAG_EMBEDDING_BATCH_SIZE,
              "samples_per_bucket": args.samples_per_bucket,
              "writes_to_database": False, "buckets": []}
    print(json.dumps(report), flush=True)
    if pending:
        embedder = DenseEmbedder(Config)
        started = perf_counter()
        embedder.encode(["Requisitos de titulacion en la Universidad de Sonora"])
        report["cold_query_seconds"] = round(perf_counter() - started, 3)
        started = perf_counter()
        embedder.encode(["Como solicitar una beca universitaria"])
        report["warm_query_seconds"] = round(perf_counter() - started, 3)
        import torch

        report["torch_version"] = torch.__version__
        report["torch_threads"] = torch.get_num_threads()
        report["cuda_available"] = torch.cuda.is_available()
        estimates = []
        for name, lower, upper in (("short", 0, 175), ("medium", 175, 350), ("long", 350, float("inf"))):
            bucket = sorted((text for text in pending if lower <= len(text.split()) < upper),
                            key=lambda text: len(text.split()))
            if not bucket:
                continue
            sample_size = min(args.samples_per_bucket, len(bucket))
            samples = [bucket[min(len(bucket) - 1, int((i + 0.5) * len(bucket) / sample_size))]
                       for i in range(sample_size)]
            started = perf_counter()
            embedder.encode(samples)
            elapsed = perf_counter() - started
            estimate = elapsed / sample_size * len(bucket)
            estimates.append(estimate)
            result = {"name": name, "pending_contents": len(bucket),
                      "sample_words": [len(text.split()) for text in samples],
                      "sample_seconds": round(elapsed, 3),
                      "seconds_per_content": round(elapsed / sample_size, 3),
                      "estimated_seconds": round(estimate, 3)}
            report["buckets"].append(result)
            print(json.dumps(result), flush=True)
        report["estimated_embedding_hours"] = round(sum(estimates) / 3600, 3)
    else:
        report["estimated_embedding_hours"] = 0
    report["caveat"] = (
        "Small sample; estimate excludes SQL writes, model startup/download and other workloads. "
        "Index batches depend on document boundaries. Actual time can differ substantially."
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
