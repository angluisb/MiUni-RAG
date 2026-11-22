# Prepare mismatch sources without changing the database

Use `scripts/prepare_source_refresh.py` to fetch only the reviewed `Stored/live content mismatch` candidates. Preparation never imports the indexer, writes the database, calls a model, or assigns current status. Actual replacement requires the separate archive/guarded-indexing workflow.

## Quick path

```powershell
# Plan only: no HTTP requests.
venv/Scripts/python.exe scripts/prepare_source_refresh.py --source-inventory .cache/versioned-refresh-apply/source-inventory.json --output-dir .cache/source-refresh-20261121

# Explicitly fetch a three-source pilot through the existing crawl policy.
venv/Scripts/python.exe scripts/prepare_source_refresh.py --fetch --limit 3 --source-inventory .cache/versioned-refresh-apply/source-inventory.json --output-dir .cache/source-refresh-20261121

# Resume all 150 candidates; validated pilot snapshots are not fetched again.
venv/Scripts/python.exe scripts/prepare_source_refresh.py --fetch --source-inventory .cache/versioned-refresh-apply/source-inventory.json --output-dir .cache/source-refresh-20261121
```

The default output is `.cache/source-refresh-<UTC-date>`. Keep preparation output private and outside Git. Use a new output directory for a new snapshot; the script refuses unrelated or differently bound directories. `--pending` selects the reviewed JSON input, not arbitrary URLs. `--limit`, `--max-bytes`, `--timeout`, and `--delay` must be positive; defaults are 150 sources, 5 MiB per decoded response body, 20 seconds per request, and 0.5 seconds minimum per origin. Robots rules may require longer delays. These are request/size bounds, not a total batch deadline.

## Outputs

| File | Purpose |
| --- | --- |
| `report.json` | Per-source checkpoint, outcome/reason, safe response headers, final URL, fetch timestamp and robots decisions. |
| `raw/<UUID>-<SHA256>.html` | Exact fetched HTML body bytes; never replaced. |
| `receipts/<UUID>.json` | Immutable source identity, raw hash, provenance and extraction settings used for resume validation. |
| `metadata.json` | Successfully prepared pages, using canonical original source URLs and raw paths. |
| `candidate_chunks.jsonl` | Complete chunk sets from the existing HTML `build_chunks` function, not partial-source deltas. |
| `guards.json` | Version 1 `sources` list with canonical `source_url`, `source_id`, and expected `temporal_status: desconocido`. |

On resume, source URL/UUID, extraction settings, raw directory and SHA256 must match before a receipt is reused. A corrupt cached snapshot is reported and excluded without a replacement fetch. Output reports and aggregate candidate files are checkpoints and can change; raw snapshots and receipts cannot. Avoid concurrent invocations against one output directory.

## Safety and limitations

- `--source-inventory` accepts `{version: 1, sources: [{source_url, source_id, source_type, category}]}` from a read-only canonical inventory. Every batch identity must match exactly; original source types and categories are preserved. Without it, category is null, never guessed from review groups. Use the same inventory for planning, pilot and resume; it is bound to the output directory.
- Category matching is exact. Non-mismatch candidates are untouched. Duplicate identities or a URL/UUID mismatch reject the entire input before fetching. UUIDs use the existing URL namespace identity.
- Public institutional host rules and `CrawlPolicy` guard resource and redirect requests. Robots denial or unavailable policy is a skip/failure, never permission to bypass it. Sessions do not use ambient proxy/netrc settings.
- Only HTTP 200 HTML/XHTML is supported. PDF URLs or responses, errors, empty/oversized bodies, out-of-scope pages and content below the existing minimum substantive word count are not candidates. The reviewed 150-source batch contains no PDF URLs.
- Before extraction, raw bytes must decode as strict UTF-8. Invalid byte sequences are retained with their provenance but skipped as `skipped_encoding`; they are never silently converted into replacement characters. Valid UTF-8 is then handled by the existing extractor and its paragraph sliding window, maximum 512 words, overlap 100 words (capped by the existing chunker), and minimum 175 substantive words.
- Fetch dates and `Last-Modified` headers are provenance, NOT publication/effective dates. Candidate chunks have no new temporal document metadata; guards expect the prior unknown state. Authority review must establish any later current classification separately.
- Safe response headers are allowlisted; cookies, authorization and exception messages are not logged. No credentials or entire private profiles are needed.
- Inspect `prepared_count` and every per-source status before applying. A successful process exit means the bounded preparation completed, not that every source was usable. Preparation is not archival or an ingestion-success receipt.

## Verification

```powershell
venv/Scripts/python.exe -m unittest discover -s tests -p test_prepare_source_refresh.py -v
venv/Scripts/python.exe -m unittest discover -s tests -p test_ingestion_robots.py -v
```

Tests use mocked HTTP responses; actual fetching and guarded database apply are separate operator actions.

## Applied refresh batch

The reviewed 150-source run produced 118 complete candidates (195 chunks), 31 inadequate pages and one non-UTF-8 page. The 118 candidates were refreshed after a verified local backup and dry-run. Their prior rows were archived outside Git; all 370 other source records and their chunks were verified unchanged. All 118 refreshed records remain `desconocido`; this ingestion updated content, not temporal validity. The 32 unprepared mismatch sources and 69 other evidence gaps remain untouched.
