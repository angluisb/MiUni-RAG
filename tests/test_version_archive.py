import io
import json
from contextlib import redirect_stdout, redirect_stderr
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

from app.rag.version_archive import load_refresh_guard, read_archive, validate_archive_directory, write_archive
from scripts import index_embeddings as cli
import test_rag_postgres as base_postgres


class ArchiveFileTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="rag-version-archive-tests-"))
        print(f"\nArchive test scratch retained for parent cleanup: {self.directory}")

    def test_content_addressed_archive_is_idempotent_and_detects_corruption(self):
        snapshot = {"schema_version": 1, "document": {"id": "x"}, "chunks": []}
        path = write_archive(self.directory, snapshot)
        before = path.stat().st_mtime_ns
        self.assertEqual(write_archive(self.directory, snapshot), path)
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertEqual(json.loads(path.read_text()), snapshot)
        path.write_text("corrupt")
        with self.assertRaisesRegex(ValueError, "digest"):
            write_archive(self.directory, snapshot)
        self.assertEqual(path.read_text(), "corrupt")

    def test_archive_path_must_be_absolute_and_outside_repository(self):
        for path in (Path("relative"), Path(__file__).resolve().parents[1] / "archives"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_archive_directory(path)

    def test_fsync_failure_never_publishes_archive(self):
        with patch("app.rag.version_archive.os.fsync", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                write_archive(self.directory, {"chunks": []})
        self.assertEqual(list(self.directory.glob("*.json")), [])


@unittest.skipUnless(os.getenv("RUN_RAG_DB_TESTS") == "1", "Set RUN_RAG_DB_TESTS=1 for PostgreSQL tests")
class VersionArchivePostgresTests(unittest.TestCase):
    chunks = base_postgres.PostgresTests.chunks
    def setUp(self):
        base_postgres.PostgresTests.setUp(self)
        self.archive_directory = Path(tempfile.mkdtemp(prefix="rag-version-db-tests-"))
        print(f"\nArchive DB scratch retained for parent cleanup: {self.archive_directory}")
        self.url = "https://test.unison.mx/becas"
        self.indexer.index_document(self.chunks(["becas", "calendario", "horarios"]))

    def snapshot(self):
        document = self.connection.execute("SELECT to_jsonb(d) AS row FROM documentofuente d WHERE referencia=%s", (self.url,)).fetchone()["row"]
        chunks = self.connection.execute("SELECT to_jsonb(c) || jsonb_build_object('embedding', c.embedding::text) AS row FROM rag_chunk c WHERE source_url=%s ORDER BY chunk_index, id", (self.url,)).fetchall()
        return document, [c["row"] for c in chunks]

    def test_full_preimage_stale_vectors_and_other_sources_preserved(self):
        other_url = "https://test.unison.mx/other"
        self.indexer.index_document(self.chunks(["other"], other_url))
        other = self.connection.execute("SELECT to_jsonb(c) AS row FROM rag_chunk c WHERE source_url=%s", (other_url,)).fetchall()
        before, chunks = self.snapshot()
        self.embedder.calls.clear()
        result = self.indexer.index_document(self.chunks(["becas"]), archive_directory=self.archive_directory,
                                            expected_source_id=before["id"], expected_temporal_status="desconocido")
        self.assertEqual(result["embedded"], 0)
        self.assertEqual(self.embedder.calls, [])
        self.assertEqual(result["deleted_stale"], 2)
        archive = read_archive(next(self.archive_directory.glob("*.json")))
        self.assertEqual(archive["document"], before)
        self.assertEqual(archive["chunks"], chunks)
        self.assertEqual(archive["chunk_count"], 3)
        self.assertEqual(other, self.connection.execute("SELECT to_jsonb(c) AS row FROM rag_chunk c WHERE source_url=%s", (other_url,)).fetchall())
        self.assertEqual(archive["kind"], "source_preimage")
        self.assertEqual(self.snapshot()[0]["id"], before["id"])

    def test_guards_fail_before_model_work_and_mutations(self):
        before = self.snapshot()
        self.embedder.calls.clear()
        cases = ({"expected_source_id": uuid4()}, {"expected_temporal_status": "vigente"})
        for guard in cases:
            with self.subTest(guard=guard), self.assertRaises(ValueError):
                self.indexer.index_document(self.chunks(["changed"]), archive_directory=self.archive_directory, **guard)
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.embedder.calls, [])
        self.assertEqual(list(self.archive_directory.glob("*.json")), [])

    def test_archive_failure_rolls_back_without_model_work(self):
        before = self.snapshot()
        self.embedder.calls.clear()
        with patch("app.rag.version_archive.write_archive", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.indexer.index_document(self.chunks(["changed"]), archive_directory=self.archive_directory)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.embedder.calls, [])

    def test_archive_publication_failure_preserves_database_and_skips_embedding(self):
        before = self.snapshot()
        self.embedder.calls.clear()
        with patch("app.rag.version_archive.os.link", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.indexer.index_document(
                    self.chunks(["changed content"]), archive_directory=self.archive_directory
                )
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.embedder.calls, [])
        self.assertEqual(list(self.archive_directory.glob("*.json")), [])

    def test_missing_or_duplicate_canonical_source_rejected(self):
        with self.assertRaises(ValueError):
            self.indexer.index_document(self.chunks(["missing"], self.url + "/missing"), archive_directory=self.archive_directory)
        self.connection.execute("INSERT INTO documentofuente (id,titulo,tipo_origen,referencia,ultima_actualizacion) VALUES (%s,'duplicate','html',%s,now())", (uuid4(), self.url))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.indexer.index_document(self.chunks(["changed"]), archive_directory=self.archive_directory)
        self.assertEqual(self.snapshot(), before)

    def test_repeat_refresh_keeps_each_distinct_preimage(self):
        first = self.snapshot()
        self.indexer.index_document(self.chunks(["new version"]), archive_directory=self.archive_directory)
        second = self.snapshot()
        self.indexer.index_document(self.chunks(["newer version"]), archive_directory=self.archive_directory)
        archives = [read_archive(path) for path in self.archive_directory.glob("*.json")]
        self.assertEqual(len(archives), 2)
        self.assertCountEqual([item["document"] for item in archives], [first[0], second[0]])
        self.assertCountEqual([item["chunks"] for item in archives], [first[1], second[1]])

    def test_failed_model_leaves_preimage_not_success_receipt(self):
        before = self.snapshot()
        self.embedder.encode = lambda texts: (_ for _ in ()).throw(RuntimeError("model failed"))
        with self.assertRaisesRegex(RuntimeError, "model failed"):
            self.indexer.index_document(self.chunks(["new unique text"]), archive_directory=self.archive_directory)
        self.assertEqual(self.snapshot(), before)
        archive = read_archive(next(self.archive_directory.glob("*.json")))
        self.assertEqual(archive["document"], before[0])
        self.assertNotIn("committed", archive)


class RefreshCliTests(unittest.TestCase):
    def test_guard_rejects_missing_duplicate_and_malformed_entries(self):
        url = "https://test.unison.mx/guard"
        entry = {"source_url": url, "source_id": str(uuid4()), "temporal_status": "desconocido"}
        for payload in ([entry, entry], [], [{**entry, "source_id": None}],
                        [{**entry, "source_url": None}], [{**entry, "temporal_status": None}]):
            with self.subTest(payload=payload), patch.object(Path, "read_text", return_value=json.dumps({"version": 1, "sources": payload})):
                with self.assertRaises(ValueError):
                    load_refresh_guard(Path("guard.json"), [url])

    def test_dry_run_validates_guard_without_database_model_or_archive_writes(self):
        url = "https://test.unison.mx/guard"
        chunk = base_postgres.PostgresTests.chunks(self, ["test"], url)[0]
        entry = {"source_url": url, "source_id": str(uuid4()), "temporal_status": "desconocido"}
        outside = Path.home() / "MiUni-test-planned-archive"
        with patch.object(cli, "load_documents", return_value={url: [chunk]}), \
             patch.object(Path, "read_text", return_value=json.dumps({"version": 1, "sources": [entry]})), \
             patch.object(cli, "RagRepository") as repository, \
             patch.object(cli, "DenseEmbedder") as model, \
             patch("app.rag.version_archive.write_archive") as archive, \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["--input", "input.jsonl", "--dry-run", "--refresh-guard", "guard.json",
                                       "--version-archive-dir", str(outside)]), 0)
        repository.return_value.connect.assert_not_called()
        repository.return_value.check.assert_not_called()
        model.assert_not_called()
        archive.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["planned_version_archive_dir"], str(outside))

    def test_flags_must_be_paired_and_plain_dry_run_remains_unchanged(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["--refresh-guard", "guard.json"])
        chunk = base_postgres.PostgresTests.chunks(self, ["test"])[0]
        with patch.object(cli, "load_documents", return_value={chunk.source_url: [chunk]}), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["--input", "input.jsonl", "--dry-run"]), 0)
        self.assertEqual(json.loads(output.getvalue()), {"documents": 1, "chunks": 1, "dry_run": True})
