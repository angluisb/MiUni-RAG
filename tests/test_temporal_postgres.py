"""Exercise prepared temporal SQL on TEMP copies, never migrate public tables."""
from contextlib import contextmanager
import os
import unittest

from app.core.config import Settings
from app.rag.embeddings import vector_literal
from app.rag.indexing import ChunkIndexer
from app.rag.models import InputChunk
from app.rag.repository import RagRepository
from app.rag.temporal import TemporalIntent


@unittest.skipUnless(os.getenv("RUN_RAG_DB_TESTS") == "1", "Set RUN_RAG_DB_TESTS=1 for PostgreSQL tests")
class TemporalPostgresTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(RAG_TEMPORAL_FILTER_ENABLED=True)
        connection = RagRepository(self.settings).connect()
        self.addCleanup(connection.close)
        connection.autocommit = True
        connection.execute("CREATE TEMP TABLE documentofuente (LIKE public.documentofuente INCLUDING ALL)")
        connection.execute("CREATE TEMP TABLE rag_chunk (LIKE public.rag_chunk INCLUDING ALL)")
        # Explicit pg_temp qualification prevents DDL reaching the live schema.
        connection.execute("""ALTER TABLE pg_temp.documentofuente
            ADD COLUMN IF NOT EXISTS temporal_status text NOT NULL DEFAULT 'desconocido',
            ADD COLUMN IF NOT EXISTS document_year integer,
            ADD COLUMN IF NOT EXISTS academic_period text,
            ADD COLUMN IF NOT EXISTS effective_from timestamptz,
            ADD COLUMN IF NOT EXISTS effective_to timestamptz,
            ADD COLUMN IF NOT EXISTS last_verified_at timestamptz,
            ADD COLUMN IF NOT EXISTS superseded_by uuid""")

        class TemporaryRepository(RagRepository):
            @contextmanager
            def connect(self):
                with connection.transaction():
                    yield connection

        class Embedder:
            def encode(self, texts):
                return [vector_literal([1.0] + [0.0] * 1023) for _ in texts]

        self.repository = TemporaryRepository(self.settings)
        self.vector = Embedder().encode(["query"])[0]
        indexer = ChunkIndexer(self.settings, self.repository, Embedder())
        for key, status, period, expired in (
                ("current", "vigente", "2025-2", False),
                ("historical", "historico", "2024-2", False),
                ("replaced", "reemplazado", "2023-2", False),
                ("unknown", "desconocido", "2025-2", False),
                ("expired", "vigente", "2025-2", True)):
            url = f"https://test.unison.mx/temporal/{key}"
            indexer.index_document([InputChunk(
                id=key, source_type="html", source_url=url, document_title=key,
                chunk_index=0, content=f"Becas universitarias {key}")])
            connection.execute("""UPDATE pg_temp.documentofuente
                SET temporal_status = %s, academic_period = %s,
                    effective_to = CASE WHEN %s THEN now() - interval '1 day' ELSE NULL END
                WHERE referencia = %s""", (status, period, expired, url))

    def keys(self, search, intent, limit=20):
        query = self.vector if search == self.repository.vector_search else "becas"
        return {hit.source_url.rsplit("/", 1)[1] for hit in search(query, limit, intent)}

    def test_default_current_excludes_unknown_expired_and_historical_for_both_branches(self):
        for search in (self.repository.vector_search, self.repository.lexical_search):
            self.assertEqual(self.keys(search, TemporalIntent()), {"current"})

    def test_historical_and_period_filters_apply_before_candidate_limit(self):
        for search in (self.repository.vector_search, self.repository.lexical_search):
            self.assertEqual(self.keys(search, TemporalIntent("historico")),
                             {"current", "historical", "replaced", "expired"})
            self.assertEqual(self.keys(search, TemporalIntent("periodo_especifico", "2024-2"), 1),
                             {"historical"})


if __name__ == "__main__":
    unittest.main()
