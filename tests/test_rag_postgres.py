"""Opt-in PostgreSQL tests against TEMP copies of the migrated tables, never live rows."""
import os
import unittest
from contextlib import contextmanager

from app.core.config import Settings
from app.rag.embeddings import vector_literal
from app.rag.indexing import ChunkIndexer
from app.rag.models import InputChunk
from app.rag.repository import RagRepository


class FakeEmbedder:
    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.extend(texts)
        return [vector_literal([1.0 if "beca" in text else 0.0,
                                0.0 if "beca" in text else 1.0] + [0.0] * 1022)
                for text in texts]


@unittest.skipUnless(os.getenv("RUN_RAG_DB_TESTS") == "1", "Set RUN_RAG_DB_TESTS=1 for PostgreSQL tests")
class PostgresTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings()
        self.connection = RagRepository(self.settings).connect()
        self.connection.autocommit = True
        self.addCleanup(self.connection.close)
        self.connection.execute("CREATE TEMP TABLE documentofuente (LIKE public.documentofuente INCLUDING ALL)")
        self.connection.execute("CREATE TEMP TABLE rag_chunk (LIKE public.rag_chunk INCLUDING ALL)")
        self.connection.execute(
            "ALTER TABLE rag_chunk ADD FOREIGN KEY (documento_fuente_id) REFERENCES documentofuente(id)")
        connection = self.connection

        class TemporaryRepository(RagRepository):
            @contextmanager
            def connect(self):
                with connection.transaction():
                    yield connection

        self.repository = TemporaryRepository(self.settings)
        self.embedder = FakeEmbedder()
        self.indexer = ChunkIndexer(self.settings, self.repository, self.embedder)

    def chunks(self, texts, url="https://test.unison.mx/becas"):
        return [InputChunk(id=f"chunk-{index}", source_type="html", source_url=url,
                           document_title="Becas", category="tramites", chunk_index=index,
                           content=text, metadata={"page_start": 1})
                for index, text in enumerate(texts)]

    def test_reindex_reuses_vectors_and_updates_metadata_without_duplicate_rows(self):
        chunks = self.chunks(["Requisitos de becas", "Calendario escolar"])
        self.assertEqual(self.indexer.index_document(chunks)["embedded"], 2)
        before = self.connection.execute("SELECT id, embedded_at FROM rag_chunk ORDER BY chunk_index").fetchall()
        chunks[0].metadata["last_seen_at"] = "2026-10-19"
        self.assertEqual(self.indexer.index_document(chunks)["embedded"], 0)
        after = self.connection.execute("SELECT id, embedded_at FROM rag_chunk ORDER BY chunk_index").fetchall()
        self.assertEqual(before, after)
        self.assertEqual(len(self.embedder.calls), 2)
        self.assertEqual(self.connection.execute("SELECT count(*) AS n FROM documentofuente").fetchone()["n"], 1)
        self.assertEqual(self.connection.execute(
            "SELECT metadata->>'last_seen_at' AS seen FROM rag_chunk WHERE chunk_index = 0"
        ).fetchone()["seen"], "2026-10-19")

    def test_shorter_source_prunes_stale_chunks_but_preserves_other_documents(self):
        self.indexer.index_document(self.chunks(["becas", "calendario", "horarios"]))
        self.indexer.index_document(self.chunks(["Otra fuente"], "https://test.unison.mx/otra"))
        result = self.indexer.index_document(self.chunks(["becas nuevas"]))
        self.assertEqual(result["deleted_stale"], 2)
        self.assertEqual(self.connection.execute("SELECT count(*) AS n FROM rag_chunk").fetchone()["n"], 2)

    def test_cosine_lexical_and_pipeline_compatibility(self):
        self.indexer.index_document(self.chunks(["Requisitos de becas estudiantiles", "Calendario escolar"]))
        embedding = self.embedder.encode(["becas"])[0]
        self.assertEqual(self.repository.vector_search(embedding, 2)[0].content, "Requisitos de becas estudiantiles")
        lexical = self.repository.lexical_search("becas", 5)
        self.assertEqual(len(lexical), 1)
        self.assertEqual(lexical[0].content, "Requisitos de becas estudiantiles")
        self.assertEqual(self.repository.lexical_search("zzzyyynonexistent", 5), [])
        self.settings.RAG_EMBEDDING_PIPELINE_VERSION = "new-version"
        self.assertEqual(self.repository.vector_search(embedding, 5), [])
        self.assertEqual(self.indexer.index_document(self.chunks(["Requisitos de becas estudiantiles"]))["embedded"], 1)
        self.assertEqual(len(self.repository.vector_search(embedding, 5)), 1)

    def test_duplicate_content_across_sources_reuses_embedding(self):
        self.indexer.index_document(self.chunks(["becas"]))
        result = self.indexer.index_document(self.chunks(["becas"], "https://test.unison.mx/otra"))
        self.assertEqual(result["embedded"], 0)
        self.assertEqual(len(self.embedder.calls), 1)

    def test_embedding_failure_keeps_previous_complete_document(self):
        self.indexer.index_document(self.chunks(["becas", "calendario"]))

        class FailingEmbedder:
            def encode(self, texts):
                raise RuntimeError("model unavailable")

        self.indexer.embedder = FailingEmbedder()
        with self.assertRaisesRegex(RuntimeError, "model unavailable"):
            self.indexer.index_document(self.chunks(["contenido cambiado"]))
        contents = self.connection.execute("SELECT content FROM rag_chunk ORDER BY chunk_index").fetchall()
        self.assertEqual([row["content"] for row in contents], ["becas", "calendario"])

    def test_sql_error_rolls_back_already_updated_chunks(self):
        import psycopg

        self.indexer.index_document(self.chunks(["becas", "calendario"]))
        self.connection.execute("ALTER TABLE rag_chunk ADD CHECK (content <> 'rechazado')")
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.indexer.index_document(self.chunks(["becas modificadas", "rechazado"]))
        contents = self.connection.execute("SELECT content FROM rag_chunk ORDER BY chunk_index").fetchall()
        self.assertEqual([row["content"] for row in contents], ["becas", "calendario"])
