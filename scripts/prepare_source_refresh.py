"""Prepare reviewed mismatch sources without model calls or database writes."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import requests

ROOT = Path(__file__).resolve().parents[1]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))

from app.rag.crawl_policy import CrawlPolicy, CrawlPolicyError
from scripts.ingest_html import (
    build_chunks, DEFAULT_MAX_WORDS, DEFAULT_OVERLAP_WORDS, MIN_CHUNK_WORDS,
)
from scripts.scrape_web import host_is_allowed, normalize_url, USER_AGENT

DEFAULT_PENDING = ROOT / 'data/sources/document_temporal_review_pending.json'
MISMATCH_CATEGORY = 'Stored/live content mismatch'
SETTINGS = {'extractor': 'scripts.ingest_html.build_chunks', 'max_words': DEFAULT_MAX_WORDS,
            'overlap_words': DEFAULT_OVERLAP_WORDS, 'min_words': MIN_CHUNK_WORDS,
            'decoding': 'utf-8/errors=replace'}
SAFE_HEADERS = {'content-type', 'content-length', 'content-encoding', 'etag', 'last-modified',
                'date', 'cache-control', 'expires', 'vary'}
MARKER = '.source-refresh.json'


def allowed_url(url, discovered_from=None):
    """Keep the existing institutional host policy, without credentials or ports."""
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in {'http', 'https'} or parsed.username is not None
                or parsed.password is not None or parsed.port is not None or parsed.fragment):
            return False
        return host_is_allowed(url, discovered_from or url)
    except ValueError:
        return False


def positive_int(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError('Must be positive')
    return result


def positive_float(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError('Must be finite and positive')
    return result


def select_sources(pending: Path, limit: int = 150):
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError('Limit must be a positive integer')
    payload = json.loads(pending.read_text(encoding='utf-8-sig'))
    if not isinstance(payload, dict) or not isinstance(payload.get('sources'), list):
        raise ValueError('Pending input must contain a sources list')
    selected, seen_urls, seen_ids = [], set(), set()
    for item in payload['sources']:
        if not isinstance(item, dict):
            raise ValueError('Invalid source record')
        if item.get('category') != MISMATCH_CATEGORY:
            continue
        url, identity = item.get('source_url'), item.get('source_id')
        if (not isinstance(url, str) or normalize_url(url) != url or not allowed_url(url)
                or identity != str(uuid5(NAMESPACE_URL, url))):
            raise ValueError('Mismatch source URL/UUID identity is invalid')
        if url in seen_urls or identity in seen_ids:
            raise ValueError('Duplicate mismatch source identity')
        seen_urls.add(url)
        seen_ids.add(identity)
        selected.append(item)
    return selected[:limit]


def write_json(path, payload):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def immutable_bytes(path, content):
    """Never replace a previous raw snapshot or source receipt."""
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError('Immutable output collision')
        return
    with path.open('xb') as stream:
        stream.write(content)


def prepare_output(output, sources):
    binding = {'version': 1, 'purpose': 'mismatch-source-refresh',
               'sources': [{'source_url': s['source_url'], 'source_id': s['source_id'],
                            'source_type': s.get('source_type', 'html'),
                            'category': s.get('ingestion_category')} for s in sources],
               'settings': SETTINGS}
    if output.exists() and any(output.iterdir()):
        marker = output / MARKER
        if not marker.is_file() or json.loads(marker.read_text(encoding='utf-8')) != binding:
            raise ValueError('Output directory is not an identical owned refresh batch; use a new directory')
    else:
        output.mkdir(parents=True, exist_ok=True)
        immutable_bytes(output / MARKER, (json.dumps(binding, sort_keys=True) + '\n').encode())
    (output / 'raw').mkdir(exist_ok=True)
    (output / 'receipts').mkdir(exist_ok=True)


def reusable_receipt(path, source, output):
    if not path.exists():
        return None
    receipt = json.loads(path.read_text(encoding='utf-8'))
    raw = Path(receipt['raw_html_path'])
    if (receipt['source_url'] != source['source_url'] or receipt['source_id'] != source['source_id']
            or receipt['extraction_settings'] != SETTINGS
            or raw.resolve().parent != (output / 'raw').resolve()
            or hashlib.sha256(raw.read_bytes()).hexdigest() != receipt['sha256']):
        raise ValueError('Cached provenance/hash mismatch')
    return receipt


def fetch_one(source, output, policy, max_bytes, timeout):
    base = {'source_url': source['source_url'], 'source_id': source['source_id']}
    receipt_path = output / 'receipts' / (source['source_id'] + '.json')
    try:
        receipt = reusable_receipt(receipt_path, source, output)
    except (OSError, ValueError, KeyError, TypeError):
        return {**base, 'status': 'failed_cache_integrity'}
    if receipt is not None:
        return receipt
    if source.get('source_type', 'html') != 'html' or urlsplit(source['source_url']).path.lower().endswith('.pdf'):
        return {**base, 'status': 'skipped_unsupported'}
    event_start = len(policy.events)
    record = {**base, 'status': 'failed_fetch'}
    reply = None
    try:
        reply = policy.get(source['source_url'], discovered_from=source['source_url'], stream=True, timeout=timeout)
        record.update({'final_url': reply.url, 'http_status': reply.status_code,
                       'response_headers': {k.lower(): v for k, v in reply.headers.items() if k.lower() in SAFE_HEADERS},
                       'fetched_at': datetime.now(timezone.utc).isoformat()})
        if reply.status_code != 200:
            record['status'] = 'failed_http'
            return record
        if reply.headers.get('content-type', '').split(';', 1)[0].strip().lower() not in {'text/html', 'application/xhtml+xml'}:
            record['status'] = 'skipped_unsupported'
            return record
        length = reply.headers.get('content-length')
        if length is not None and int(length) > max_bytes:
            record['status'] = 'skipped_too_large'
            return record
        body = bytearray()
        for part in reply.iter_content(chunk_size=65536):
            body.extend(part)
            if len(body) > max_bytes:
                record['status'] = 'skipped_too_large'
                return record
        if not body:
            record['status'] = 'skipped_empty'
            return record
        digest = hashlib.sha256(body).hexdigest()
        raw_path = (output / 'raw' / (source['source_id'] + '-' + digest + '.html')).resolve()
        immutable_bytes(raw_path, bytes(body))
        record.update({'status': 'fetched', 'sha256': digest, 'content_length': len(body),
                       'raw_html_path': str(raw_path), 'extraction_settings': SETTINGS})
    except CrawlPolicyError as exc:
        record.update({'status': exc.outcome + '_policy', 'reason': exc.reason})
    except requests.Timeout:
        record['status'] = 'failed_timeout'
    except requests.RequestException:
        record['status'] = 'failed_request'
    except (OSError, ValueError):
        record['status'] = 'failed_content_or_storage'
    finally:
        record['policy_outcomes'] = policy.events[event_start:]
        if reply is not None:
            reply.close()
    if record['status'] == 'fetched':
        immutable_bytes(receipt_path, (json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n').encode('utf-8'))
    return record


def apply_inventory(sources, inventory):
    """Preserve original ingestion categories, never review labels or groups."""
    if inventory is None:
        return [{**source, 'ingestion_category': None} for source in sources]
    payload = json.loads(Path(inventory).read_text(encoding='utf-8-sig'))
    if payload.get('version') != 1 or not isinstance(payload.get('sources'), list):
        raise ValueError('Invalid source inventory')
    records = {}
    for record in payload['sources']:
        url = record.get('source_url')
        if (not isinstance(url, str) or url in records
                or record.get('source_id') != str(uuid5(NAMESPACE_URL, url))
                or record.get('source_type') not in {'html', 'pdf'}
                or not (record.get('category') is None or isinstance(record['category'], str))):
            raise ValueError('Invalid or duplicate inventory identity')
        records[url] = record
    result = []
    for source in sources:
        record = records.get(source['source_url'])
        if record is None or record['source_id'] != source['source_id']:
            raise ValueError('Source inventory missing canonical mismatch identity')
        result.append({**source, 'ingestion_category': record.get('category'),
                       'source_type': record['source_type']})
    return result


def prepare(pending, output, *, fetch=False, limit=150, max_bytes=5 * 1024 * 1024,
            timeout=20.0, delay=0.5, policy=None, source_inventory=None):
    """Checkpoint each source. Inject a CrawlPolicy in tests; never bypass it."""
    if (not isinstance(max_bytes, int) or max_bytes <= 0 or not math.isfinite(timeout)
            or timeout <= 0 or not math.isfinite(delay) or delay <= 0):
        raise ValueError('Fetch bounds must be finite and positive')
    # Bind the complete authorized batch, not the pilot prefix, so a pilot can
    # resume into the remaining candidates without weakening source identity.
    batch = select_sources(Path(pending), sys.maxsize)
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError('Limit must be a positive integer')
    batch = apply_inventory(batch, source_inventory)
    sources = batch[:limit]
    output = Path(output).resolve()
    prepare_output(output, batch)
    session = None
    if fetch and policy is None:
        session = requests.Session()
        session.trust_env = False
        session.headers.update({'User-Agent': USER_AGENT})
        policy = CrawlPolicy(session, USER_AGENT, allowed_url, min_delay=delay, timeout=timeout)
    records, metadata, chunks, guards = [], [], [], []
    report = {'version': 1, 'mode': 'fetch' if fetch else 'plan', 'selected_count': len(sources),
              'prepared_count': 0, 'sources': records}

    def checkpoint():
        if fetch:
            write_json(output / 'metadata.json', metadata)
            write_json(output / 'guards.json', {'version': 1, 'sources': guards})
            temporary = output / 'candidate_chunks.jsonl.tmp'
            with temporary.open('w', encoding='utf-8') as stream:
                for chunk in chunks:
                    stream.write(json.dumps(chunk, ensure_ascii=False) + '\n')
            temporary.replace(output / 'candidate_chunks.jsonl')
        report['prepared_count'] = len(metadata)
        write_json(output / 'report.json', report)

    try:
        for source in sources:
            if not fetch:
                records.append({'source_url': source['source_url'], 'source_id': source['source_id'], 'status': 'planned'})
                checkpoint()
                continue
            try:
                record = fetch_one(source, output, policy, max_bytes, timeout)
                if record['status'] == 'fetched':
                    try:
                        Path(record['raw_html_path']).read_bytes().decode('utf-8', errors='strict')
                    except UnicodeDecodeError:
                        record = {**record, 'status': 'skipped_encoding', 'reason': 'non_utf8_source_bytes'}
                if record['status'] == 'fetched':
                    page = {'url': source['source_url'], 'source_id': source['source_id'],
                            'title': source.get('title'), 'category': source.get('ingestion_category'),
                            'raw_html_path': record['raw_html_path'], 'last_seen_at': record['fetched_at'],
                            'sha256': record['sha256'], 'provenance_path': str(output / 'receipts' / (source['source_id'] + '.json'))}
                    candidates = build_chunks([page], DEFAULT_MAX_WORDS, DEFAULT_OVERLAP_WORDS)
                    # Never partially replace a source: all original chunker output or none.
                    if not candidates or sum(len(c['content'].split()) for c in candidates) < MIN_CHUNK_WORDS:
                        record = {**record, 'status': 'skipped_inadequate'}
                    else:
                        metadata.append(page)
                        chunks.extend(candidates)
                        guards.append({'source_url': source['source_url'], 'source_id': source['source_id'],
                                       'temporal_status': 'desconocido'})
                        record = {**record, 'status': 'prepared', 'chunk_count': len(candidates)}
            except (OSError, ValueError, KeyError, TypeError):
                record = {'source_url': source['source_url'], 'source_id': source['source_id'], 'status': 'failed_preparation'}
            records.append(record)
            checkpoint()
        checkpoint()
    finally:
        if session is not None:
            session.close()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pending', type=Path, default=DEFAULT_PENDING, help='Reviewed pending-source JSON')
    parser.add_argument('--source-inventory', type=Path, help='Version 1 canonical source inventory preserving original source_type/category')
    parser.add_argument('--output-dir', type=Path, default=ROOT / '.cache' / ('source-refresh-' + datetime.now(timezone.utc).date().isoformat()), help='New private preparation directory, or identical batch to resume')
    parser.add_argument('--fetch', action='store_true', help='Explicitly enable bounded public HTTP fetching; default only writes a plan')
    parser.add_argument('--limit', type=positive_int, default=150, help='Maximum mismatch sources (default: 150)')
    parser.add_argument('--max-bytes', type=positive_int, default=5 * 1024 * 1024, help='Maximum decoded HTTP body bytes per source')
    parser.add_argument('--timeout', type=positive_float, default=20.0, help='Per-request timeout in seconds')
    parser.add_argument('--delay', type=positive_float, default=0.5, help='Minimum per-origin delay in seconds; robots may increase it')
    args = parser.parse_args(argv)
    try:
        report = prepare(args.pending, args.output_dir, fetch=args.fetch, limit=args.limit,
                         max_bytes=args.max_bytes, timeout=args.timeout, delay=args.delay,
                         source_inventory=args.source_inventory)
    except (ValueError, OSError):
        parser.exit(2, 'Preparation input/output validation failed; no database writes performed.\n')
    print(json.dumps({'mode': report['mode'], 'selected_count': report['selected_count'],
                      'prepared_count': report['prepared_count']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
