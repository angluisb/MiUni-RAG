import json
from contextlib import contextmanager
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, call

from app.core.config import Settings
from app.rag.repository import RagRepository
from app.rag.retrieval import RetrievalService


class TemporalTests(unittest.IsolatedAsyncioTestCase):
    def service(self):
        settings = Settings(_env_file=None, RAG_TEMPORAL_FILTER_ENABLED=True,
                            RAG_MEASURE_RETRIEVAL_PERFORMANCE=False)
        repository = Mock()
        repository.vector_search.return_value = []
        repository.lexical_search.return_value = []
        embedder = Mock()
        embedder.encode.return_value = ["vector"]
        return RetrievalService(settings, repository, embedder, Mock())

    async def test_period_intent_filters_both_branches_before_fusion(self):
        service = self.service()
        payload = json.dumps({"alcance_temporal": "periodo_especifico", "periodo": "2025-2",
                              "hyde_doc": "documentary query"})
        result = await service.retrieve("becas 2025-2", AsyncMock(return_value=payload))
        intent = service.repository.vector_search.call_args.args[2]
        self.assertEqual(intent.scope, "periodo_especifico")
        self.assertEqual(intent.period, "2025-2")
        self.assertEqual(service.repository.lexical_search.call_args.args[2], intent)
        self.assertEqual(service.repository.lexical_search.call_args.args[0], "becas 2025-2")
        service.embedder.encode.assert_has_calls([
            call(["becas 2025-2"]), call(["documentary query"])
        ], any_order=True)
        self.assertEqual(service.embedder.encode.call_count, 2)
        self.assertEqual(result.metrics["temporal_scope"], "periodo_especifico")

    async def test_invalid_json_and_missing_period_fall_back_to_current_original_query(self):
        for payload in ("not JSON", '{"alcance_temporal":"historico"}',
                        '{"alcance_temporal":"historico","periodo":false,"hyde_doc":"passage"}',
                        '{"alcance_temporal":"periodo_especifico","hyde_doc":"passage"}'):
            service = self.service()
            await service.retrieve("original", AsyncMock(return_value=payload))
            service.embedder.encode.assert_called_once_with(["original"])
            intent = service.repository.vector_search.call_args.args[2]
            self.assertEqual(intent.scope, "vigente")
            self.assertIsNone(intent.period)


class TemporalSqlTests(unittest.TestCase):
    def test_current_period_and_history_are_parameterized_before_ordering(self):
        from app.rag.temporal import TemporalIntent

        for intent, expected in ((TemporalIntent(), ["vigente"]),
                                 (TemporalIntent("historico"), ["vigente", "historico", "reemplazado"]),
                                 (TemporalIntent("periodo_especifico", "2025-2"),
                                  ["vigente", "historico", "reemplazado"])):
            connection = Mock()
            connection.execute.return_value.fetchall.return_value = []

            class Repository(RagRepository):
                @contextmanager
                def connection(self):
                    yield connection

            repo = Repository(Settings(_env_file=None, RAG_TEMPORAL_FILTER_ENABLED=True))
            for method, query in ((repo.vector_search, "vector"), (repo.lexical_search, "becas")):
                method(query, 5, intent)
                sql, values = connection.execute.call_args.args
                self.assertIn("documentofuente", sql)
                self.assertIn(expected, values)
                self.assertLess(sql.index("temporal_status"), sql.index("ORDER BY"))
                if intent.period:
                    self.assertNotIn("2025-2", sql)
                    self.assertIn("2025-2", values)


if __name__ == "__main__":
    unittest.main()
