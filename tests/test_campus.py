import unittest
from unittest.mock import Mock, patch

from app.services.campus_service import location_answer, location_target
from app.services import llm_service


PLACES = [
    {"id": "central", "nombre": "Biblioteca Central", "map_url": "/mapa?lugar=central"},
    {"id": "medicina", "nombre": "Biblioteca de medicina", "map_url": "/mapa?lugar=medicina"},
    {"id": "8a", "nombre": "8A - Dirección de servicios escolares", "map_url": "/mapa?lugar=8a"},
]


class CampusTests(unittest.TestCase):
    def test_exact_names_codes_accents_and_typo(self):
        for question, expected in [
            ("¿Dónde está la Biblioteca Central?", "central"),
            ("donde esta la bibloteca central", "central"),
            ("Dónde queda el edificio 8A por favor?", "8a"),
            ("ubicación de Biblioteca de medicina", "medicina"),
        ]:
            self.assertIn(f"(/mapa?lugar={expected})",
                          location_answer(location_target(question), PLACES))

    def test_unknown_generic_or_ambiguous_names_do_not_select_a_place(self):
        for target in ("biblioteca", "rectoria", "18a", "biblioteca central no"):
            self.assertIsNone(location_answer(target, PLACES))
        duplicate = {**PLACES[0], "id": "otra-central"}
        self.assertIsNone(location_answer("biblioteca central", PLACES + [duplicate]))

    def test_document_and_mixed_questions_still_need_the_existing_pipeline(self):
        for question in (
            "Qué becas puedo pedir?",
            "Dónde está la Biblioteca Central y a qué hora abre?",
            "Cuál es el horario de la Biblioteca Central?",
        ):
            self.assertIsNone(location_target(question))


class CampusChatTests(unittest.IsolatedAsyncioTestCase):
    async def test_navigation_and_catalog_listing_bypass_model_with_canonical_links(self):
        retriever = Mock()
        retriever.repository.list_campus_places.return_value = PLACES
        with patch.object(llm_service.Config, "RAG_ENABLED", True), \
             patch.object(llm_service, "_get_retriever", return_value=retriever), \
             patch.object(llm_service, "_get_llm") as llm:
            for question in ("¿Cómo llego a Biblioteca Central?", "Cómo llegar a Biblioteca Central?"):
                answer = await llm_service.get_chat_response(question)
                self.assertIn("/mapa?lugar=central", answer)
            answer = await llm_service.get_chat_response("¿Qué lugares hay en el campus?")
            self.assertIn("/mapa?lugar=central", answer)
            self.assertIn("/mapa?lugar=medicina", answer)
            self.assertNotIn("/mapa?lugar=Biblioteca", answer)
        llm.assert_not_called()
        retriever.retrieve.assert_not_called()

    async def test_json_and_stream_use_real_catalog_without_calling_model_or_embeddings(self):
        retriever = Mock()
        retriever.repository.list_campus_places.return_value = PLACES
        with patch.object(llm_service.Config, "RAG_ENABLED", True), \
             patch.object(llm_service, "_get_retriever", return_value=retriever), \
             patch.object(llm_service, "_get_llm") as llm:
            answer = await llm_service.get_chat_response("donde esta la bibloteca central")
            streamed = "".join([s async for s in llm_service.stream_chat_response(
                "donde esta la bibloteca central")])
        self.assertEqual(answer, streamed)
        self.assertIn("(/mapa?lugar=central)", answer)
        llm.assert_not_called()
        retriever.retrieve.assert_not_called()
