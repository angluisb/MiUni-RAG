from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from app.core.config import Settings
from app.rag.models import InputChunk, text_hash


def load_documents(paths: list[Path]) -> dict[str, list[InputChunk]]:
    documents = defaultdict(list)
    keys = {}
    for path in paths:
        with path.open(encoding="utf-8") as source:
            for line_number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    chunk = InputChunk.model_validate_json(line)
                    key = (chunk.source_url, chunk.chunk_index)
                    if key in keys:
                        existing = keys[key]
                        if existing.content != chunk.content or existing.source_type != chunk.source_type:
                            raise ValueError(f"Contenido contradictorio para {chunk.id}")
                        categories = existing.metadata.setdefault(
                            "source_categories", [existing.category] if existing.category else [])
                        if chunk.category and chunk.category not in categories:
                            categories.append(chunk.category)
                        continue
                    keys[key] = chunk
                    documents[chunk.source_url].append(chunk)
                except ValueError as exc:
                    raise ValueError(f"{path}:{line_number}: {exc}") from exc
    for url, chunks in documents.items():
        chunks.sort(key=lambda chunk: chunk.chunk_index)
        if [chunk.chunk_index for chunk in chunks] != list(range(len(chunks))):
            raise ValueError(f"Indices incompletos para {url}; proporciona el documento completo")
        if len({chunk.source_type for chunk in chunks}) != 1:
            raise ValueError(f"Tipos de fuente inconsistentes para {url}")
    return dict(documents)


class ChunkIndexer:
    def __init__(self, settings: Settings, repository, embedder):
        self.settings = settings
        self.repository = repository
        self.embedder = embedder

    def index_document(self, chunks: list[InputChunk]) -> dict:
        from psycopg.types.json import Jsonb

        if not chunks:
            raise ValueError("Se necesita un documento completo con al menos un chunk")
        source = chunks[0]
        if any(c.source_url != source.source_url for c in chunks):
            raise ValueError("No se pueden mezclar documentos")
        if sorted(c.chunk_index for c in chunks) != list(range(len(chunks))):
            raise ValueError("Se necesita el documento completo con indices consecutivos")
        texts = {text_hash(chunk.content): chunk.content for chunk in chunks}
        settings = self.settings
        with self.repository.connect() as conn:
            # Serialize reimports of the same source, including creation of its parent row.
            conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (source.source_url,))
            cached = conn.execute(
                """SELECT content_sha256, embedding::text AS embedding, embedded_at
                   FROM rag_chunk WHERE content_sha256 = ANY(%s)
                     AND embedding IS NOT NULL AND embedded_at IS NOT NULL AND embedding_model = %s
                     AND embedding_dimension = %s
                     AND metadata->>'embedding_pipeline_version' = %s
                     AND metadata->>'embedding_input_sha256' = content_sha256""",
                (list(texts), settings.RAG_EMBEDDING_MODEL, settings.RAG_EMBEDDING_DIMENSION,
                 settings.RAG_EMBEDDING_PIPELINE_VERSION),
            ).fetchall()
            cache = {row["content_sha256"]: (row["embedding"], row["embedded_at"]) for row in cached}
            missing = [digest for digest in texts if digest not in cache]
            batch_size = settings.RAG_EMBEDDING_BATCH_SIZE
            for start in range(0, len(missing), batch_size):
                batch = missing[start:start + batch_size]
                vectors = self.embedder.encode([texts[digest] for digest in batch])
                if len(vectors) != len(batch):
                    raise ValueError("El modelo no devolvio un embedding por chunk")
                now = datetime.now(timezone.utc)
                cache.update({digest: (vector, now) for digest, vector in zip(batch, vectors)})

            document = conn.execute(
                "SELECT id FROM documentofuente WHERE referencia = %s ORDER BY id LIMIT 1",
                (source.source_url,),
            ).fetchone()
            document_id = document["id"] if document else uuid5(NAMESPACE_URL, source.source_url)
            conn.execute(
                """INSERT INTO documentofuente (id, titulo, tipo_origen, referencia, ultima_actualizacion)
                   VALUES (%s, %s, %s, %s, now()) ON CONFLICT (id) DO UPDATE
                   SET titulo = EXCLUDED.titulo, tipo_origen = EXCLUDED.tipo_origen,
                       ultima_actualizacion = now()""",
                (document_id, source.document_title, source.source_type, source.source_url),
            )
            for chunk in chunks:
                digest = text_hash(chunk.content)
                embedding, embedded_at = cache[digest]
                metadata = {**chunk.metadata, "chunk_id": chunk.id,
                            "content_sha256": digest,
                            "embedding_model": settings.RAG_EMBEDDING_MODEL,
                            "embedding_dimension": settings.RAG_EMBEDDING_DIMENSION,
                            "embedding_created_at": embedded_at.isoformat(),
                            "embedding_input_sha256": digest,
                            "embedding_pipeline_version": settings.RAG_EMBEDDING_PIPELINE_VERSION}
                conn.execute(
                    """INSERT INTO rag_chunk
                       (id, documento_fuente_id, source_type, source_url, document_title,
                        category, chunk_index, content, metadata, content_sha256,
                        embedding_model, embedding_dimension, embedded_at, embedding)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                       ON CONFLICT (source_url, chunk_index) DO UPDATE SET
                         documento_fuente_id = EXCLUDED.documento_fuente_id,
                         source_type = EXCLUDED.source_type, document_title = EXCLUDED.document_title,
                         category = EXCLUDED.category, content = EXCLUDED.content,
                         metadata = EXCLUDED.metadata, content_sha256 = EXCLUDED.content_sha256,
                         embedding_model = EXCLUDED.embedding_model,
                         embedding_dimension = EXCLUDED.embedding_dimension,
                         embedded_at = EXCLUDED.embedded_at, embedding = EXCLUDED.embedding,
                         updated_at = now()""",
                    (uuid5(document_id, str(chunk.chunk_index)), document_id, chunk.source_type,
                     chunk.source_url, chunk.document_title, chunk.category, chunk.chunk_index,
                     chunk.content, Jsonb(metadata), digest, settings.RAG_EMBEDDING_MODEL,
                     settings.RAG_EMBEDDING_DIMENSION, embedded_at, embedding),
                )
            # Only prune the fully supplied document, never other sources in the database.
            deleted = conn.execute(
                "DELETE FROM rag_chunk WHERE source_url = %s AND NOT (chunk_index = ANY(%s))",
                (source.source_url, [chunk.chunk_index for chunk in chunks]),
            ).rowcount
        return {"chunks": len(chunks), "embedded": len(missing),
                "reused": len(chunks) - len(missing), "deleted_stale": deleted}
