from contextlib import contextmanager
from unittest.mock import Mock, patch
import unittest

from app.core.config import Settings
from app.rag.repository import RagRepository


class PoolTests(unittest.TestCase):
    def test_reuses_pool_and_returns_transaction_context_then_closes(self):
        repo = RagRepository(Settings(_env_file=None, DATABASE_URL="postgresql://test"))
        pool = Mock()
        connection = Mock()
        pool.connection.return_value.__enter__ = Mock(return_value=connection)
        pool.connection.return_value.__exit__ = Mock(return_value=False)
        with patch("psycopg_pool.ConnectionPool", return_value=pool) as constructor:
            with repo.connection() as first:
                self.assertIs(first, connection)
            with repo.connection() as second:
                self.assertIs(second, connection)
            constructor.assert_called_once()
            self.assertEqual(constructor.call_args.kwargs["max_size"], 4)
            self.assertEqual(constructor.call_args.kwargs["max_waiting"], 16)
            self.assertEqual(constructor.call_args.kwargs["min_size"], 0)
            self.assertEqual(pool.connection.call_count, 2)
            repo.close()
            pool.close.assert_called_once()

    def test_overridden_raw_connect_stays_transactionally_isolated(self):
        expected = object()

        class TemporaryRepository(RagRepository):
            @contextmanager
            def connect(self):
                yield expected

        repo = TemporaryRepository(Settings(_env_file=None))
        with repo.connection() as connection:
            self.assertIs(connection, expected)


if __name__ == "__main__":
    unittest.main()
