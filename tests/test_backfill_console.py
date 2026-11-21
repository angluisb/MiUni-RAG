"""Backfill JSON remains usable on Windows legacy-encoded consoles."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


class BackfillConsoleTests(unittest.TestCase):
    def test_report_preserves_unicode_urls_on_cp1252_stdout(self):
        code = r"""
from scripts import backfill_document_metadata as cli
cli.load_manifest = lambda path: {}
cli.RagRepository = lambda settings: object()
cli.backfill_metadata = lambda *args, **kwargs: {
    "dry_run": True, "source_url": "https://example.edu/gui\u0301a", "affected_rows": 0}
raise SystemExit(cli.main(["--manifest", "unused.json"]))
"""
        environment = os.environ.copy()
        environment["PYTHONIOENCODING"] = "cp1252"
        result = subprocess.run([sys.executable, "-c", code],
                                cwd=Path(__file__).resolve().parents[1],
                                env=environment, capture_output=True, text=True,
                                encoding="cp1252", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["source_url"], "https://example.edu/gui\u0301a")
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["affected_rows"], 0)
