from __future__ import annotations

from app.core.config import Settings
from app.rag.models import SearchHit


class RagRepository:
    def __init__(self, settings: Settings):
        self.settings = settings

    def connect(self):
        if not self.settings.DATABASE_URL.strip():
            raise ValueError("Configura DATABASE_URL en .env antes de consultar PostgreSQL")
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(
            self.settings.DATABASE_URL,
            row_factory=dict_row,
            connect_timeout=self.settings.RAG_DB_CONNECT_TIMEOUT_SECONDS,
            options=f"-c statement_timeout={self.settings.RAG_DB_STATEMENT_TIMEOUT_MS}",
        )

    def check(self) -> dict:
        with self.connect() as conn:
            version = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
            if not version:
                raise RuntimeError("Falta CREATE EXTENSION vector en esta base de datos")
            table = conn.execute("SELECT to_regclass('rag_chunk') AS name").fetchone()
            if not table["name"]:
                raise RuntimeError(
                    "Falta rag_chunk. Aplica las migraciones de MiUni.Api "
                    "(AddRagChunksPgvector) con ASPNETCORE_ENVIRONMENT=Docker."
                )
            column = conn.execute(
                "SELECT format_type(atttypid, atttypmod) AS type FROM pg_attribute "
                "WHERE attrelid = 'rag_chunk'::regclass AND attname = 'embedding'"
            ).fetchone()
            if not column or column["type"] != "vector(1024)":
                raise RuntimeError("rag_chunk.embedding debe ser vector(1024)")
            # Check the shared columns as well, so an incomplete migration fails early.
            conn.execute("SELECT documento_fuente_id, source_type, source_url, document_title, "
                         "category, chunk_index, content, metadata, content_sha256, "
                         "embedding_model, embedding_dimension, embedded_at, search_tsv "
                         "FROM rag_chunk LIMIT 0")
            conn.execute("SELECT id, titulo, tipo_origen, referencia FROM documentofuente LIMIT 0")
            counts = conn.execute(
                "SELECT count(*) AS chunks, count(embedding) AS embedded_chunks FROM rag_chunk"
            ).fetchone()
            indexes = conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() "
                "AND tablename = 'rag_chunk' ORDER BY indexname"
            ).fetchall()
            return {"pgvector_version": version["extversion"], **counts,
                    "indexes": [row["indexname"] for row in indexes]}

    @staticmethod
    def _hits(rows) -> list[SearchHit]:
        return [SearchHit(
            id=str(row["id"]), source_url=row["source_url"],
            document_title=row["document_title"], content=row["content"],
            metadata=row["metadata"], score=float(row["score"]),
        ) for row in rows]

    def vector_search(self, embedding: str, top_n: int) -> list[SearchHit]:
        with self.connect() as conn:
            # An ANN index must scan at least as many candidates as requested.
            conn.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(max(40, top_n)),))
            conn.execute("SELECT set_config('hnsw.iterative_scan', 'strict_order', true)")
            rows = conn.execute(
                """SELECT id, source_url, document_title, content, metadata,
                          1 - (embedding <=> %s::vector) AS score
                   FROM rag_chunk
                   WHERE embedding IS NOT NULL AND embedding_model = %s
                     AND embedding_dimension = %s
                     AND metadata->>'embedding_pipeline_version' = %s
                   ORDER BY embedding <=> %s::vector LIMIT %s""",
                (embedding, self.settings.RAG_EMBEDDING_MODEL,
                 self.settings.RAG_EMBEDDING_DIMENSION,
                 self.settings.RAG_EMBEDDING_PIPELINE_VERSION, embedding, top_n),
            ).fetchall()
        return self._hits(rows)

    def lexical_search(self, question: str, top_n: int) -> list[SearchHit]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT id, source_url, document_title, content, metadata,
                          ts_rank_cd(search_tsv, query) AS score
                   FROM rag_chunk, websearch_to_tsquery('spanish', %s) query
                   WHERE search_tsv @@ query
                   ORDER BY score DESC, id LIMIT %s""",
                (question, top_n),
            ).fetchall()
        return self._hits(rows)
