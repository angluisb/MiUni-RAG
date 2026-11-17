import io
import json
import os
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from app.core.config import Settings
from app.rag.document_metadata import DocumentMetadata
from app.rag.embeddings import vector_literal
from app.rag.indexing import ChunkIndexer
from app.rag.models import InputChunk
from app.rag.repository import RagRepository
from scripts import backfill_document_metadata as cli


class BackfillCliTests(unittest.TestCase):
    def test_cli_defaults_to_dry_run_and_apply_requires_backup(self):
        repository = Mock()
        with patch.object(cli, "load_manifest", return_value={}), \
             patch.object(cli, "RagRepository", return_value=repository), \
             patch.object(cli, "backfill_metadata", return_value={"dry_run": True}) as run, \
             redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--manifest", "manifest.json"]), 0)
        self.assertFalse(run.call_args.kwargs["apply"])
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            cli.main(["--manifest", "manifest.json", "--apply"])
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            cli.main(["--manifest", "manifest.json", "--apply", "--backup", "outside.json"])

    def test_cli_validates_manifest_before_connecting(self):
        with patch.object(cli, "load_manifest", side_effect=ValueError("bad manifest")), \
             patch.object(cli, "RagRepository") as repository:
            with self.assertRaisesRegex(ValueError, "bad manifest"):
                cli.main(["--manifest", "manifest.json"])
        repository.assert_not_called()


@unittest.skipUnless(os.getenv("RUN_RAG_DB_TESTS") == "1", "Set RUN_RAG_DB_TESTS=1 for PostgreSQL tests")
class CanonicalMetadataPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backup_dir = Path(tempfile.mkdtemp(prefix="rag-temporal-backfill-tests-"))
        print(f"\nMetadata test backups retained for parent cleanup: {cls.backup_dir}")

    def setUp(self):
        self.settings = Settings(RAG_TEMPORAL_FILTER_ENABLED=True)
        self.conn = RagRepository(self.settings).connect()
        self.addCleanup(self.conn.close)
        self.conn.autocommit = True
        self.conn.execute("CREATE TEMP TABLE documentofuente (LIKE public.documentofuente INCLUDING ALL)")
        self.conn.execute("CREATE TEMP TABLE rag_chunk (LIKE public.rag_chunk INCLUDING ALL)")
        self.conn.execute("ALTER TABLE pg_temp.documentofuente ADD FOREIGN KEY (superseded_by) "
                          "REFERENCES pg_temp.documentofuente(id) ON DELETE RESTRICT")
        self.conn.execute("ALTER TABLE pg_temp.rag_chunk ADD FOREIGN KEY (documento_fuente_id) "
                          "REFERENCES pg_temp.documentofuente(id)")
        conn = self.conn

        class TemporaryRepository:
            @contextmanager
            def connect(self):
                with conn.transaction():
                    yield conn

        self.repository = TemporaryRepository()
        self.embedder = Mock()
        self.embedder.encode.side_effect = lambda texts: [vector_literal([1.0] + [0.0] * 1023) for _ in texts]
        self.indexer = ChunkIndexer(self.settings, self.repository, self.embedder)
        self.url = "https://test.unison.mx/metadata"
        self.indexer.index_document(self.chunks())
        self.database = self.conn.info.dbname

    def chunks(self, metadata=None, url=None):
        return [InputChunk(id="metadata-0", source_type="html", source_url=url or self.url,
                           document_title="Metadata test", chunk_index=0, content="Becas metadata",
                           metadata={"page_start": 3, **(metadata or {})})]

    def declaration(self, **changes):
        values = {"temporal_status": "vigente", "document_year": 2026,
                  "academic_period": "2026-2", "last_verified_at": "2026-11-17T10:00:00Z",
                  "evidence": {"reviewed_by": "operator", "rationale": "Checked official publication",
                               "verification_urls": [self.url]}}
        values.update(changes)
        return DocumentMetadata.model_validate(values)

    def source(self):
        return self.conn.execute("SELECT * FROM pg_temp.documentofuente WHERE referencia = %s",
                                 (self.url,)).fetchone()

    def chunks_snapshot(self):
        return self.conn.execute("SELECT to_jsonb(c) AS row FROM pg_temp.rag_chunk c ORDER BY id").fetchall()

    def apply(self, manifest, suffix="apply"):
        return cli.backfill_metadata(self.repository, manifest, apply=True,
                                     backup=self.backup_dir / f"{uuid4()}-{suffix}.json",
                                     expected_database=self.database)

    def test_indexing_persists_then_omission_preserves_and_explicit_null_clears(self):
        self.assertEqual(self.source()["temporal_status"], "desconocido")
        payload = self.declaration().model_dump(mode="json", exclude_unset=True)
        self.indexer.index_document(self.chunks({"document_metadata": payload}))
        self.assertEqual(self.source()["temporal_status"], "vigente")
        self.assertEqual(self.source()["document_year"], 2026)
        self.indexer.index_document(self.chunks())
        self.assertEqual(self.source()["temporal_status"], "vigente")
        self.assertEqual(self.source()["document_year"], 2026)
        self.indexer.index_document(self.chunks({"document_metadata": {"document_year": None}}))
        self.assertIsNone(self.source()["document_year"])
        self.assertEqual(self.source()["temporal_status"], "vigente")

    def test_dry_run_apply_backup_idempotence_and_unchanged_chunks(self):
        before = self.source()
        chunks = self.chunks_snapshot()
        manifest = {self.url: self.declaration(source_id=before["id"])}
        dry = cli.backfill_metadata(self.repository, manifest)
        self.assertTrue(dry["dry_run"])
        self.assertEqual(dry["affected_rows"], 1)
        self.assertEqual(before, self.source())
        applied = self.apply(manifest)
        self.assertEqual(applied["affected_rows"], 1)
        backup = json.loads(Path(applied["backup"]).read_text(encoding="utf-8"))
        self.assertEqual(backup["before"][0]["temporal_status"], "desconocido")
        self.assertNotIn("password", backup["database"])
        self.assertEqual(self.source()["temporal_status"], "vigente")
        self.assertEqual(self.apply(manifest)["affected_rows"], 0)
        self.assertEqual(chunks, self.chunks_snapshot())
        self.assertEqual(self.apply({})["affected_rows"], 0)
        self.assertEqual(self.source()["temporal_status"], "vigente")
        self.assertEqual(chunks, self.chunks_snapshot())

    def test_backup_failure_prevents_all_updates(self):
        before = self.source()
        with patch.object(cli, "write_backup", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.apply({self.url: self.declaration()})
        self.assertEqual(before, self.source())

    def test_unknown_source_wrong_identity_replacement_and_database_rejected(self):
        before = self.source()
        cases = ({self.url + "/missing": self.declaration()},
                 {self.url: self.declaration(source_id=uuid4())},
                 {self.url: self.declaration(temporal_status="reemplazado", superseded_by=uuid4())},
                 {self.url: self.declaration(temporal_status="reemplazado", superseded_by=before["id"])})
        for manifest in cases:
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                self.apply(manifest)
            self.assertEqual(before, self.source())
        with self.assertRaisesRegex(ValueError, "database"):
            cli.backfill_metadata(self.repository, {}, expected_database="incorrect-database")

    def test_constraint_failure_rolls_back_entire_manifest(self):
        import psycopg

        second = self.url + "/second"
        self.indexer.index_document(self.chunks(url=second))
        self.conn.execute("ALTER TABLE pg_temp.documentofuente ADD CHECK (document_year IS DISTINCT FROM 1999)")
        before = self.conn.execute("SELECT to_jsonb(d) AS row FROM pg_temp.documentofuente d ORDER BY id").fetchall()
        chunks = self.chunks_snapshot()
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.apply({self.url: self.declaration(), second: self.declaration(document_year=1999)})
        self.assertEqual(before, self.conn.execute(
            "SELECT to_jsonb(d) AS row FROM pg_temp.documentofuente d ORDER BY id").fetchall())
        self.assertEqual(chunks, self.chunks_snapshot())

    def test_merged_dates_are_revalidated_and_missing_fields_do_not_downgrade(self):
        self.apply({self.url: self.declaration(effective_from="2026-01-01T00:00:00Z")})
        before = self.source()
        with self.assertRaisesRegex(ValueError, "effective_from"):
            self.apply({self.url: DocumentMetadata(effective_to="2025-01-01T00:00:00Z")})
        self.assertEqual(before, self.source())
        self.apply({self.url: DocumentMetadata(document_year=None)})
        self.assertEqual(self.source()["temporal_status"], "vigente")
        self.assertIsNone(self.source()["document_year"])
        self.assertEqual(self.source()["academic_period"], "2026-2")

    def test_indexing_rejects_inconsistent_metadata_before_connecting(self):
        first = self.chunks()[0]
        second = first.model_copy(update={"chunk_index": 1,
                                         "metadata": {"document_metadata": {"document_year": 2025}}})
        repository = Mock()
        with self.assertRaisesRegex(ValueError, "Inconsistent"):
            ChunkIndexer(self.settings, repository, self.embedder).index_document([first, second])
        repository.connect.assert_not_called()
