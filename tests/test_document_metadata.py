import json
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

from app.rag.document_metadata import DocumentMetadata, load_manifest, metadata_for_chunks
from app.rag.indexing import load_documents
from app.rag.models import InputChunk
from scripts import ingest_html, ingest_pdf


URL = "https://test.unison.mx/source"


def verified(**changes):
    return dict(temporal_status="vigente", document_year=2026,
                academic_period="2026-2", last_verified_at="2026-11-17T10:00:00Z",
                evidence={"reviewed_by": "operator", "rationale": "Reviewed official publication",
                          "verification_urls": [URL]}, **changes)


def chunk(**changes):
    return InputChunk(id="a", source_url=URL, source_type="html", document_title="Test",
                      content="Content", chunk_index=0, **changes)


class DocumentMetadataTests(unittest.TestCase):
    def test_manifest_validates_exact_url_identity_and_preserves_omissions(self):
        payload = {"version": 1, "sources": [{"source_url": URL, **verified()}]}
        with patch.object(Path, "open", mock_open(read_data=json.dumps(payload))):
            manifest = load_manifest(Path("manifest.json"))
        metadata = manifest[URL]
        self.assertEqual(metadata.canonical_values()["temporal_status"], "vigente")
        self.assertNotIn("effective_to", metadata.canonical_values())
        self.assertEqual(DocumentMetadata().canonical_values(), {})
        self.assertEqual(DocumentMetadata(temporal_status="desconocido").canonical_values(),
                         {"temporal_status": "desconocido"})

    def test_rejects_invalid_metadata_and_unverified_classification(self):
        for data in ({"temporal_status": "vigente"}, {"temporal_status": "bad"},
                     {"document_year": 999}, {"document_year": True},
                     {"academic_period": "2026-other"},
                     {"last_verified_at": "2026-11-17T10:00:00"},
                     {"effective_from": "2026-11-18T00:00:00Z", "effective_to": "2026-11-17T00:00:00Z"},
                     {"superseded_by": "not-uuid"}, {"temporal_status": None},
                     {"surprise": "ignored?"}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                DocumentMetadata.model_validate(data)

    def test_rejects_conflicting_document_metadata_before_writes(self):
        first = chunk(metadata={"document_metadata": verified()})
        second = first.model_copy(update={"chunk_index": 1,
                                 "metadata": {"document_metadata": {"temporal_status": "desconocido"}}})
        with self.assertRaisesRegex(ValueError, "Inconsistent"):
            metadata_for_chunks([first, second])
        self.assertEqual(metadata_for_chunks([first]).temporal_status, "vigente")

    def test_chunk_envelope_validates_without_losing_legacy_metadata(self):
        item = chunk(metadata={"page_start": 3, "source_categories": ["a"],
                               "document_metadata": verified()})
        self.assertEqual(item.metadata["page_start"], 3)
        self.assertEqual(item.metadata["source_categories"], ["a"])
        with self.assertRaises(ValueError):
            chunk(metadata={"document_metadata": {"temporal_status": "vigente"}})

    def test_manifest_rejects_duplicate_sources_and_unknown_fields(self):
        for payload in ({"version": 1, "sources": [{"source_url": URL}, {"source_url": URL}]},
                        {"version": 1, "sources": [{"source_url": URL, "typo": 1}]}):
            with patch.object(Path, "open", mock_open(read_data=json.dumps(payload))):
                with self.assertRaises(ValueError):
                    load_manifest(Path("manifest.json"))

    def test_html_and_pdf_manifest_integration_preserves_chunk_metadata(self):
        manifest = {URL: DocumentMetadata.model_validate(verified())}
        html = "<main><h1>Becas</h1><p>" + "Requirements " * 200 + "</p></main>"
        with patch.object(ingest_html, "load_manifest", return_value=manifest), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "read_text", return_value=html):
            rows = ingest_html.build_chunks([{"url": URL, "raw_html_path": "source.html",
                                             "category": "becas"}], 512, 100,
                                            temporal_manifest=Path("manifest.json"))
        self.assertTrue(rows)
        self.assertEqual(rows[0]["metadata"]["document_metadata"]["document_year"], 2026)
        self.assertEqual(rows[0]["category"], "becas")
        with patch.object(ingest_pdf, "load_manifest", return_value=manifest), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(ingest_pdf, "extract_pdf_pages", return_value=(
                 [{"page": 3, "text": "Requirements " * 200}], "fake")):
            rows = ingest_pdf.build_chunks([{"url": URL, "raw_pdf_path": "source.pdf",
                                            "download_status": "downloaded"}], 512, 100,
                                           temporal_manifest=Path("manifest.json"))
        self.assertTrue(rows)
        self.assertEqual(rows[0]["metadata"]["page_start"], 3)
        self.assertEqual(rows[0]["metadata"]["document_metadata"]["temporal_status"], "vigente")

    def test_index_load_rejects_conflicting_duplicate_and_uses_manifest(self):
        row = chunk().model_dump()
        with patch.object(Path, "open", mock_open(read_data=json.dumps(row))), \
             patch("app.rag.indexing.load_manifest", return_value={URL: DocumentMetadata.model_validate(verified())}):
            documents = load_documents([Path("chunks.jsonl")], Path("manifest.json"))
        self.assertEqual(documents[URL][0].metadata["document_metadata"]["temporal_status"], "vigente")
        duplicate = {**row, "metadata": {"document_metadata": {"temporal_status": "desconocido"}}}
        with patch.object(Path, "open", mock_open(read_data=json.dumps(row) + "\n" + json.dumps(duplicate))):
            with self.assertRaisesRegex(ValueError, "Inconsistent"):
                load_documents([Path("chunks.jsonl")])
