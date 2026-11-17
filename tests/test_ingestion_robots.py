import io
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import Mock, patch

import requests

from app.rag.crawl_policy import CrawlPolicy
from scripts import download_pdfs as pdf
from scripts import scrape_web as web


ORIGIN = "https://www.unison.mx"


def response(url, status=200, body=b"User-agent: *\nAllow: /", content_type="text/plain", **headers):
    result = requests.Response()
    result.url, result.status_code = url, status
    result._content, result._content_consumed = body, True
    result.headers.update({"content-type": content_type, **headers})
    return result


class IngestionRobotsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("pathlib.Path.exists", return_value=False))
        self.stack.enter_context(patch("pathlib.Path.mkdir"))
        self.write_bytes = self.stack.enter_context(patch("pathlib.Path.write_bytes"))
        self.write_text = self.stack.enter_context(patch("pathlib.Path.write_text"))
        self.session = Mock()
        self.source = {"url": ORIGIN + "/becas.pdf", "category": "becas", "depth": 1}

    def download(self, replies, **kwargs):
        self.session.get.side_effect = replies
        policy = CrawlPolicy(self.session, pdf.USER_AGENT, pdf.host_is_allowed,
                             min_delay=0, sleeper=lambda seconds: None)
        return pdf.download_pdf(self.session, kwargs.pop("source", self.source), 7, 1,
                                kwargs.pop("include_review_required", False), "2026-11-17", policy)

    def scrape(self, replies):
        self.session.get.side_effect = replies
        self.stack.enter_context(patch.object(web.requests, "Session", return_value=self.session))
        self.stack.enter_context(patch.object(web, "load_seeds", return_value=[{"url": ORIGIN + "/start"}]))
        writer = self.stack.enter_context(patch.object(web, "write_json"))
        with redirect_stdout(io.StringIO()):
            web.scrape(0, 2, 0)
        return writer.call_args_list[0].args[1]

    def test_pdf_and_html_reject_disallowed_before_fetch_and_report_policy(self):
        robots = b"User-agent: *\nDisallow: /"
        record = self.download([response(ORIGIN + "/robots.txt", body=robots)])
        self.assertEqual(record["download_status"], "skipped_policy")
        self.assertEqual(record["policy_outcomes"][0]["outcome"], "rejected")
        self.write_bytes.assert_not_called()
        self.assertEqual(self.session.get.call_count, 1)
        self.session.reset_mock()
        records = self.scrape([response(ORIGIN + "/robots.txt", body=robots)])
        self.assertEqual(records[0]["error"], "policy_rejected")
        self.assertEqual(records[0]["policy_outcomes"][0]["outcome"], "rejected")
        self.assertEqual(self.session.get.call_count, 1)
        self.write_text.assert_not_called()

    def test_unavailable_policy_is_distinct_from_resource_http_failure(self):
        record = self.download([response(ORIGIN + "/robots.txt", status=503)])
        self.assertEqual(record["download_status"], "failed_policy")
        self.assertEqual(record["policy_outcomes"][0]["outcome"], "unavailable")
        record = self.download([response(ORIGIN + "/robots.txt", status=404),
                                response(self.source["url"], status=503)])
        self.assertEqual(record["download_status"], "failed_http")
        self.assertEqual(record["policy_outcomes"][0]["outcome"], "allowed")
        records = self.scrape([response(ORIGIN + "/robots.txt", status=429)])
        self.assertEqual(records[0]["error"], "policy_unavailable")

    def test_both_entrypoints_guard_redirects_before_external_request(self):
        record = self.download([response(ORIGIN + "/robots.txt", status=404),
                                response(self.source["url"], status=302, Location="https://evil.example/doc.pdf")])
        self.assertEqual(record["download_status"], "skipped_external_redirect")
        self.assertEqual(record["policy_outcomes"][-1]["outcome"], "rejected")
        self.assertEqual(self.session.get.call_count, 2)
        self.session.reset_mock()
        records = self.scrape([response(ORIGIN + "/robots.txt", status=404),
                               response(ORIGIN + "/start", status=302, Location="https://evil.example/")])
        self.assertEqual(records[0]["error"], "policy_rejected")
        self.assertEqual(self.session.get.call_count, 2)

    def test_cached_pdf_and_review_scope_filters_remain_network_free(self):
        with patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_bytes", return_value=b"%PDF cached"):
            record = self.download([])
        self.assertEqual(record["download_status"], "already_downloaded")
        self.assertEqual(record["content_length"], 11)
        self.assertIsNotNone(record["sha256"])
        for source, expected in [({"url": ORIGIN + "/curriculum.pdf"}, "skipped_review_required"),
                                 ({"url": ORIGIN + "/presupuesto.pdf"}, "skipped_out_of_scope"),
                                 ({"url": "https://evil.example/doc.pdf"}, "skipped_external_redirect")]:
            self.assertEqual(self.download([], source=source)["download_status"], expected)
        self.session.get.assert_not_called()

    def test_pdf_timeout_mime_size_and_success_keep_existing_fields(self):
        scenarios = [
            (requests.Timeout("timeout"), "failed_timeout"),
            (response(self.source["url"], body=b"html", content_type="text/html"), "skipped_not_pdf"),
            (response(self.source["url"], body=b"x" * (1024 * 1024 + 1), content_type="application/pdf"), "skipped_too_large"),
            (response(self.source["url"], body=b"%PDF real", content_type="application/octet-stream"), "downloaded"),
        ]
        for reply, expected in scenarios:
            with self.subTest(expected=expected):
                record = self.download([response(ORIGIN + "/robots.txt", status=410), reply])
                self.assertEqual(record["download_status"], expected)
                self.assertEqual(record["category"], "becas")
                self.assertEqual(record["depth"], 1)
                self.assertEqual(record["last_downloaded_at"], "2026-11-17")
                self.assertEqual(self.session.get.call_args.kwargs["timeout"], 7)
                self.assertFalse(self.session.get.call_args.kwargs["allow_redirects"])

    def test_html_success_preserves_metadata_and_records_admission(self):
        records = self.scrape([response(ORIGIN + "/robots.txt", status=404),
                               response(ORIGIN + "/start", body=b"<html><title>Title</title></html>", content_type="text/html")])
        self.assertEqual(records[0]["title"], "Title")
        self.assertEqual(records[0]["status"], 200)
        self.assertEqual(records[0]["policy_outcomes"][0]["reason"], "allowed_absent")
        self.write_text.assert_called_once()
        self.assertFalse(self.session.trust_env)
        self.session.headers.update.assert_called_with({"User-Agent": web.USER_AGENT})

    def test_existing_cli_flags_and_host_policy_differences_are_preserved(self):
        with patch("sys.argv", ["scrape_web", "--max-depth", "3", "--max-pages", "4", "--delay", "0.2"]):
            args = web.parse_args()
        self.assertEqual((args.max_depth, args.max_pages, args.delay), (3, 4, 0.2))
        with patch("sys.argv", ["download_pdfs", "--max-pdfs", "4", "--delay", "0.2", "--timeout", "9",
                                "--max-file-mb", "2", "--include-review-required", "--input", "in.json", "--metadata", "out.json"]):
            args = pdf.parse_args()
        self.assertEqual((args.max_pdfs, args.delay, args.timeout, args.max_file_mb, args.include_review_required),
                         (4, 0.2, 9, 2, True))
        self.assertEqual(str(args.input), "in.json")
        self.assertEqual(str(args.metadata), "out.json")
        url = "https://new-department.unison.mx/file"
        self.assertFalse(web.host_is_allowed(url))
        self.assertTrue(web.host_is_allowed(url, ORIGIN))
        self.assertTrue(pdf.host_is_allowed(url))
