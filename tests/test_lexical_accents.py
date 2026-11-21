"""Accent fallback: SQL contract mocks and opt-in isolated PostgreSQL semantics."""
from contextlib import contextmanager
import os
import unittest
import unicodedata
from unittest.mock import MagicMock

from app.core.config import Settings
from app.rag.repository import RagRepository
from app.rag.temporal import TemporalIntent


class LexicalAccentSqlTests(unittest.TestCase):
    def repository(self, batches):
        repository = RagRepository(Settings(RAG_TEMPORAL_FILTER_ENABLED=True))
        connection = MagicMock()
        connection.execute.return_value.fetchall.side_effect = batches
        repository.connection = MagicMock()
        repository.connection.return_value.__enter__.return_value = connection
        return repository, connection

    def test_zero_hits_retry_with_same_temporal_filter_and_bound_query(self):
        repository, connection = self.repository([[], []])
        question = "titulacion '); DROP TABLE rag_chunk; --"
        self.assertEqual(repository.lexical_search(question, 7, TemporalIntent("periodo_especifico", "2024-2")), [])
        self.assertEqual(connection.execute.call_count, 2)
        first, fallback = connection.execute.call_args_list
        predicate, parameters = TemporalIntent("periodo_especifico", "2024-2").predicate()
        for call in (first, fallback):
            self.assertIn(predicate, call.args[0])
            self.assertNotIn(question, call.args[0])
            self.assertEqual(call.args[1], (question, *parameters, 7))
            self.assertIn("ORDER BY score DESC, id LIMIT %s", call.args[0])

    def test_success_does_not_retry_or_replace_indexed_hits(self):
        row = dict(id="a", source_url="https://example.test", document_title="Title",
                   content="titulación", metadata={}, score=0.25)
        repository, connection = self.repository([[row]])
        hits = repository.lexical_search("titulación", 8)
        self.assertEqual([(hit.id, hit.score) for hit in hits], [("a", 0.25)])
        self.assertEqual(connection.execute.call_count, 1)

    def test_decomposed_query_is_normalized_only_on_fallback(self):
        repository, connection = self.repository([[], []])
        question = unicodedata.normalize("NFD", "titulación")
        repository.lexical_search(question, 8)
        self.assertEqual(connection.execute.call_args_list[0].args[1][0], question)
        self.assertEqual(connection.execute.call_args_list[1].args[1][0], "titulación")


@unittest.skipUnless(os.getenv("RUN_RAG_DB_TESTS") == "1", "Set RUN_RAG_DB_TESTS=1 for PostgreSQL tests")
class LexicalAccentPostgresTests(unittest.TestCase):
    def setUp(self):
        settings = Settings(RAG_TEMPORAL_FILTER_ENABLED=True)
        connection = RagRepository(settings).connect()
        self.addCleanup(connection.close)
        connection.autocommit = True
        connection.execute("""CREATE TEMP TABLE documentofuente (
            id integer PRIMARY KEY, temporal_status text, academic_period text,
            effective_from timestamptz, effective_to timestamptz)""")
        connection.execute("""CREATE TEMP TABLE rag_chunk (
            id text PRIMARY KEY, documento_fuente_id integer, source_url text,
            document_title text, content text, metadata jsonb DEFAULT '{}',
            search_tsv tsvector GENERATED ALWAYS AS
                (to_tsvector('spanish', coalesce(content, ''))) STORED)""")
        connection.execute("""INSERT INTO pg_temp.documentofuente VALUES
            (1,'vigente','2026-2',NULL,NULL), (2,'historico','2024-2',NULL,NULL),
            (3,'desconocido',NULL,NULL,NULL), (4,'vigente','2026-2',NULL,now()-interval '1 day')""")
        rows = [
            ('a', 1, 'Requisitos de titulación'), ('b', 2, 'Requisitos de titulación'),
            ('c', 3, 'Requisitos de titulación'), ('d', 4, 'Requisitos de titulación'),
            ('e', 1, 'Calendario escolar'), ('f', 1, 'Calendario escolar'),
            ('g', 1, 'pingüino académico'), ('h', 1, 'año'),
        ]
        for key, source, content in rows:
            connection.execute("""INSERT INTO pg_temp.rag_chunk
                (id,documento_fuente_id,source_url,document_title,content)
                VALUES (%s,%s,'https://example.test','Título exclusivo',%s)""", (key, source, content))

        class TemporaryRepository(RagRepository):
            @contextmanager
            def connect(self):
                with connection.transaction():
                    yield connection

        self.repository = TemporaryRepository(settings)
        self.connection = connection

    def ids(self, query, limit=8, temporal=None):
        return [hit.id for hit in self.repository.lexical_search(query, limit, temporal)]

    def test_accented_unaccented_and_decomposed_queries_exclude_ineligible_sources(self):
        for query in ("titulacion", "titulación", unicodedata.normalize("NFD", "titulación")):
            with self.subTest(query=query):
                self.assertEqual(self.ids(query), ["a"])
        self.assertEqual(self.ids("titulacion", temporal=TemporalIntent("periodo_especifico", "2024-2")), ["b"])
        self.assertEqual(self.ids("titulacion", temporal=TemporalIntent("historico")), ["a", "b", "d"])

    def test_successful_indexed_hits_scores_order_and_limit_are_unchanged(self):
        rows = self.connection.execute("""SELECT id,ts_rank_cd(search_tsv,query) AS score
            FROM rag_chunk, websearch_to_tsquery('spanish',%s) query
            WHERE search_tsv @@ query ORDER BY score DESC,id LIMIT 1""", ("calendario",)).fetchall()
        actual = self.repository.lexical_search("calendario", 1)
        self.assertEqual([(hit.id, hit.score) for hit in actual],
                         [(row['id'], float(row['score'])) for row in rows])
        self.assertEqual(self.ids("titulacion", 1), ["a"])

    def test_diaeresis_folds_but_enye_and_title_only_matches_do_not(self):
        self.assertEqual(self.ids("pinguino academico"), ["g"])
        self.assertEqual(self.ids("ano"), [])
        self.assertEqual(self.ids("año"), ["h"])
        self.assertEqual(self.ids("exclusivo"), [])
        self.assertEqual(self.ids("' OR 1=1 -- zzznonsense"), [])


if __name__ == "__main__":
    unittest.main()
