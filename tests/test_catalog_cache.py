import unittest
from unittest.mock import Mock, patch

from app.services import llm_service


class CatalogCacheTests(unittest.TestCase):
    def setUp(self):
        llm_service._get_catalog_cache.cache_clear()
        self.addCleanup(llm_service._get_catalog_cache.cache_clear)

    def test_repeated_catalog_is_cached_but_pipeline_version_invalidates_it(self):
        repository = Mock()
        repository.list_campus_places.return_value = [{"id": "canonical"}]
        with patch.object(llm_service.Config, "RAG_CACHE_MAX_ENTRIES", 2), \
             patch.object(llm_service.Config, "RAG_CATALOG_CACHE_TTL_SECONDS", 15):
            first = llm_service._catalog_places(repository)
            self.assertEqual(first, llm_service._catalog_places(repository))
            self.assertEqual(repository.list_campus_places.call_count, 1)
            with patch.object(llm_service.Config, "RAG_EMBEDDING_PIPELINE_VERSION", "new"):
                self.assertEqual(first, llm_service._catalog_places(repository))
            self.assertEqual(repository.list_campus_places.call_count, 2)

    def test_disabled_cache_keeps_previous_catalog_calls_and_errors_are_not_cached(self):
        repository = Mock()
        with patch.object(llm_service.Config, "RAG_CACHE_MAX_ENTRIES", 0):
            llm_service._catalog_places(repository)
            llm_service._catalog_places(repository)
            self.assertEqual(repository.list_campus_places.call_count, 2)
        repository.list_campus_places.side_effect = [RuntimeError("unavailable"), []]
        with self.assertRaises(RuntimeError):
            llm_service._catalog_places(repository)
        self.assertEqual(llm_service._catalog_places(repository), [])


if __name__ == "__main__":
    unittest.main()
