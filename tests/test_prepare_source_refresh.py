import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import NAMESPACE_URL, uuid5

import requests
from scripts import prepare_source_refresh as refresh
from scripts.ingest_html import build_chunks, DEFAULT_MAX_WORDS, DEFAULT_OVERLAP_WORDS
from app.rag.crawl_policy import CrawlPolicy

ORIGIN = 'https://ofertaeducativa.unison.mx'
URL = ORIGIN + '/program/'
BODY = ('<html><main><h1>Program</h1><p>' + 'student education course ' * 200 + '</p></main></html>').encode()

def source(url=URL, category='Stored/live content mismatch'):
    return {'source_id': str(uuid5(NAMESPACE_URL, url)), 'source_url': url, 'category': category, 'title': 'Program', 'group': 'offer'}

def response(url, body=b'User-agent: *\nAllow: /', mime='text/plain', status=200, **headers):
    r = requests.Response()
    r.url, r.status_code = url, status
    r._content, r._content_consumed = body, True
    r.headers.update({'content-type': mime, **headers})
    return r

class PreparationTests(unittest.TestCase):
    def test_invalid_utf8_is_not_silently_replaced_during_refresh(self):
        body = b'<html><main><p>' + b'education course student ' * 200 + b'bad \xe9 character</p></main></html>'
        report = self.prepare([response(ORIGIN + '/robots.txt'), response(URL, body, 'text/html')])
        self.assertEqual(report['prepared_count'], 0)
        record = report['sources'][0]
        self.assertEqual(record['status'], 'skipped_encoding')
        self.assertEqual(Path(record['raw_html_path']).read_bytes(), body)

    def test_utf8_raw_bytes_and_extracted_content_agree(self):
        body = ('<html><main><h1>Program</h1><p>' + 'educación student course ' * 200 + '</p></main></html>').encode('utf-8')
        report = self.prepare([response(ORIGIN + '/robots.txt'), response(URL, body, 'text/html; charset=utf-8')])
        self.assertEqual(report['prepared_count'], 1)
        record = report['sources'][0]
        self.assertEqual(Path(record['raw_html_path']).read_bytes(), body)
        self.assertEqual(record['sha256'], hashlib.sha256(body).hexdigest())
        chunks = [json.loads(line) for line in (self.output / 'candidate_chunks.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(any('educación' in chunk['content'] for chunk in chunks))

    def setUp(self):
        # Parent owns scratch cleanup.
        self.root = Path(tempfile.mkdtemp(prefix='source-refresh-tests-'))
        print('SCRATCH:', self.root)
        self.pending = self.root / 'pending.json'
        self.pending.write_text(json.dumps({'version': 1, 'sources': [source()]}), encoding='utf-8')
        self.output = self.root / 'output'
        self.session = Mock()
        self.policy = CrawlPolicy(self.session, refresh.USER_AGENT, refresh.allowed_url, min_delay=0, sleeper=lambda _: None)

    def prepare(self, replies=(), **kw):
        self.session.get.side_effect = replies
        return refresh.prepare(self.pending, self.output, fetch=True, policy=self.policy, **kw)

    def test_exact_filter_limit_and_real_batch(self):
        actual = refresh.select_sources(refresh.DEFAULT_PENDING)
        self.assertEqual(len(actual), 150)
        self.assertTrue(all(s['category'] == refresh.MISMATCH_CATEGORY for s in actual))
        self.pending.write_text(json.dumps({'sources': [source(), source(ORIGIN + '/other', 'Other')]}))
        self.assertEqual(len(refresh.select_sources(self.pending, 1)), 1)
        for bad in [0, -1]:
            with self.assertRaises(ValueError):
                refresh.select_sources(self.pending, bad)

    def test_identity_and_duplicates_rejected(self):
        for rows in [[source(), source()], [{**source(), 'source_id': 'wrong'}], [source(URL + '#fragment')], [source('https://evil.example/test')]]:
            self.pending.write_text(json.dumps({'sources': rows}))
            with self.assertRaises(ValueError):
                refresh.select_sources(self.pending)

    def test_cli_default_has_no_network_or_database(self):
        with patch.object(refresh.requests, 'Session') as session:
            self.assertEqual(refresh.main(['--pending', str(self.pending), '--output-dir', str(self.output)]), 0)
        session.assert_not_called()
        self.assertFalse((self.output / 'candidate_chunks.jsonl').exists())
        self.assertEqual(json.loads((self.output / 'report.json').read_text())['sources'][0]['status'], 'planned')

    def test_robots_denied_or_unavailable_never_fetches_resource(self):
        for status, body in [(200, b'User-agent: *\nDisallow: /'), (503, b'')]:
            with self.subTest(status=status):
                self.policy.cache.clear()
                report = self.prepare([response(ORIGIN + '/robots.txt', body, status=status)])
                self.assertEqual(self.session.get.call_count, 1)
                self.assertEqual(report['prepared_count'], 0)
                self.assertIn(report['sources'][0]['status'], ['rejected_policy', 'unavailable_policy'])
                self.session.reset_mock()

    def test_redirect_cannot_bypass_policy(self):
        report = self.prepare([response(ORIGIN + '/robots.txt'), response(URL, status=302, Location='https://evil.example/')])
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(report['prepared_count'], 0)
        self.assertEqual(report['sources'][0]['policy_outcomes'][-1]['reason'], 'host_not_allowed')

    def test_provenance_original_bytes_chunker_and_resume(self):
        report = self.prepare([response(ORIGIN + '/robots.txt'), response(URL, BODY, 'text/html; charset=utf-8', ETag='abc', **{'Set-Cookie': 'secret'})])
        self.assertEqual(report['prepared_count'], 1)
        record = report['sources'][0]
        self.assertEqual(Path(record['raw_html_path']).read_bytes(), BODY)
        self.assertEqual(record['sha256'], hashlib.sha256(BODY).hexdigest())
        self.assertNotIn('set-cookie', record['response_headers'])
        chunks = [json.loads(line) for line in (self.output / 'candidate_chunks.jsonl').read_text().splitlines()]
        metadata = json.loads((self.output / 'metadata.json').read_text())
        self.assertEqual(chunks, build_chunks(metadata, DEFAULT_MAX_WORDS, DEFAULT_OVERLAP_WORDS))
        self.assertTrue(chunks)
        self.assertTrue(all('document_metadata' not in c['metadata'] for c in chunks))
        self.assertEqual(chunks[0]['source_url'], URL)
        self.assertEqual(json.loads((self.output / 'guards.json').read_text())['sources'], [{'source_url': URL, 'source_id': source()['source_id'], 'temporal_status': 'desconocido'}])
        raw_before = Path(record['raw_html_path']).stat().st_mtime_ns
        self.session.reset_mock()
        again = self.prepare([])
        self.session.get.assert_not_called()
        self.assertEqual(again['sources'][0]['fetched_at'], record['fetched_at'])
        self.assertEqual(Path(record['raw_html_path']).stat().st_mtime_ns, raw_before)

    def test_hash_tampering_fails_closed_without_refetch(self):
        report = self.prepare([response(ORIGIN + '/robots.txt'), response(URL, BODY, 'text/html')])
        Path(report['sources'][0]['raw_html_path']).write_bytes(b'tampered')
        self.session.reset_mock()
        report = self.prepare([])
        self.session.get.assert_not_called()
        self.assertEqual(report['sources'][0]['status'], 'failed_cache_integrity')
        self.assertEqual(report['prepared_count'], 0)

    def test_pilot_resumes_remaining_batch_without_repeating_fetch(self):
        second_url = ORIGIN + '/next/'
        self.pending.write_text(json.dumps({'sources': [source(), source(second_url)]}))
        first = self.prepare([response(ORIGIN + '/robots.txt'), response(URL, BODY, 'text/html')], limit=1)
        self.assertEqual(first['prepared_count'], 1)
        self.session.reset_mock()
        resumed = self.prepare([response(second_url, BODY, 'text/html')], limit=150)
        self.assertEqual(self.session.get.call_count, 1)
        self.assertEqual(self.session.get.call_args.args[0], second_url)
        self.assertEqual(resumed['prepared_count'], 2)

    def test_invalid_content_is_skipped_and_other_source_continues(self):
        cases = [(b'', 'text/html', 200, 'skipped_empty'), (b'x'*101, 'text/html', 200, 'skipped_too_large'), (b'pdf', 'application/pdf', 200, 'skipped_unsupported'), (b'bad', 'text/html', 500, 'failed_http'), (b'<p>short</p>', 'text/html', 200, 'skipped_inadequate')]
        for i, (body, mime, status, expected) in enumerate(cases):
            self.output = self.root / str(i)
            self.policy.cache.clear()
            self.pending.write_text(json.dumps({'sources': [source(), source(ORIGIN + '/next/')]}))
            result = self.prepare([response(ORIGIN + '/robots.txt'), response(URL, body, mime, status), response(ORIGIN + '/next/', BODY, 'text/html')], max_bytes=100 if i==1 else 100000)
            self.assertEqual(result['sources'][0]['status'], expected)
            self.assertEqual(len(result['sources']), 2)
            if i != 1:
                self.assertEqual(result['sources'][1]['status'], 'prepared')

    def test_timeout_and_unsafe_output_directory(self):
        report = self.prepare([response(ORIGIN + '/robots.txt'), requests.Timeout('private error')])
        self.assertEqual(report['sources'][0]['status'], 'failed_timeout')
        self.assertNotIn('private error', json.dumps(report))
        other = self.root / 'existing'
        other.mkdir()
        (other / 'report.json').write_text('old')
        with self.assertRaises(ValueError):
            refresh.prepare(self.pending, other)
        self.assertEqual((other / 'report.json').read_text(), 'old')

    def test_inventory_category_propagates_without_review_group_guess(self):
        inventory = self.root / 'inventory.json'
        inventory.write_text(json.dumps({'version': 1, 'sources': [{
            'source_url': URL, 'source_id': source()['source_id'],
            'source_type': 'html', 'category': 'oferta_educativa'}]}))
        self.prepare([response(ORIGIN + '/robots.txt'), response(URL, BODY, 'text/html')], source_inventory=inventory)
        chunks = [json.loads(s) for s in (self.output / 'candidate_chunks.jsonl').read_text().splitlines()]
        self.assertEqual(chunks[0]['category'], 'oferta_educativa')
        self.assertEqual(chunks[0]['metadata']['section'], 'oferta_educativa')
        inventory.write_text(json.dumps({'version': 1, 'sources': []}))
        with self.assertRaises(ValueError):
            self.prepare([], source_inventory=inventory)

    def test_cli_rejects_nonpositive_bounds(self):
        for flag in ['--limit', '--max-bytes', '--timeout', '--delay']:
            with self.assertRaises(SystemExit):
                refresh.main([flag, '0'])

if __name__ == '__main__':
    unittest.main()
