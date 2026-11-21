# Temporal retrieval rollout

The Python implementation is prepared but **disabled by default** because the
shared MiUni schema migration must not be applied automatically.

1. Review the prepared `DocumentTemporalMetadata` migration in MiUni.Api.
2. Apply it only with separate database authorization. Classify institutional
   documents explicitly; unknown status must not be guessed as current.
3. Set `RAG_TEMPORAL_FILTER_ENABLED=true` and restart with warmup/readiness enabled.
   Readiness checks the temporal columns before accepting normal chat traffic.
4. Compare current, historical and academic-period questions against the benchmark.

The canonical columns belong to `documentofuente`; vector and lexical SQL filter
through `documento_fuente_id` before ORDER BY, fusion or reranking. Current queries
require `temporal_status=vigente` and compatible nullable effective dates. Historical
queries allow vigente/historico/reemplazado. Period queries additionally require the
exact `academic_period`. Unknown status is never a fallback result. No document is
deleted or rewritten by a search.

HyDE returns a validated object when the flag is enabled:

```json
{"alcance_temporal":"periodo_especifico","periodo":"2025-2","hyde_doc":"Hypothetical search passage"}
```

Scopes are `vigente`, `historico`, or `periodo_especifico`; period is null outside
period-specific retrieval. Invalid JSON/fields, timeout, or provider errors use
the original question with the safe current-only filter. Invalid responses are
not cached. The cache key separates structured and legacy prompt modes.

Lexical search starts immediately using the original question and current-only
policy while HyDE is pending. If valid HyDE requests a different scope, that
speculative result is discarded and lexical search is repeated with the validated
filter. It is never merged across policies. Cancellation awaits the asyncio
siblings; already-running SQL threads remain bounded by statement timeout/pool.

The disabled flag preserves legacy SQL and text-only HyDE until the approved
rollout. Therefore prepared code and unit tests alone do **not** prove that live
temporal filtering or the latency/quality targets have been achieved.

## Local integration verified on 2026-11-16

Both original checkouts use `feat/chatbot-optimization`; their `main` branches
were not changed. MiUni local edits were preserved on
`backup/chatbot-pre-integration-20261116` before integration.

Migration `20261116120000_DocumentTemporalMetadata` was explicitly authorized and
applied to the existing local PostgreSQL RAG database on port **5433**, after a
custom-format backup under ignored `.cache/backups/`. All 17 predecessor
migrations were already applied. Document and chunk content fingerprints were
unchanged (488 documents, 1379 chunks). Do not use the unrelated port 5432 database.

The local `.env` now sets `RAG_TEMPORAL_FILTER_ENABLED=true`; the committed default
remains false for deployments without the migration. The initial rollout left all 488 documents `desconocido`, with no verified temporal
metadata. That initially excluded every institutional document without deleting
anything. The subsequent ingestion-v2 reviewed batch classifies six sources and
restores 14 current chunks; 482 sources remain unknown. See
[the rollout verification](ingestion-v2-verification.md). Catalog/map routing is independent. Classify sources only from verified status, dates and periods;
do not bulk mark them current to make a demonstration answer work.

Use current, historical and explicit-period questions to check that unsupported
claims are not invented. Meaningful answer-quality comparisons require verified
source classifications first. The prior four Gemini measurements predate this
strict rollout and must not be described as its quality benchmark.

## Reviewed source manifest

Canonical temporal values now flow from a reviewed, exact-URL-keyed manifest
into `documentofuente`. The checked-in
`data/sources/document_temporal_metadata.json` contains 269 reviewed source records;
an empty manifest remains a supported no-op and does not reset classifications.
No status or year is automatically inferred from a URL,
filename, title, crawl time or model output.

```json
{
  "version": 1,
  "sources": [{
    "source_url": "https://example.edu/official-document.pdf",
    "source_id": "11111111-1111-4111-8111-111111111111",
    "temporal_status": "vigente",
    "document_year": 2026,
    "academic_period": "2026-2",
    "effective_from": "2026-08-01T00:00:00-07:00",
    "last_verified_at": "2026-11-17T12:00:00-07:00",
    "evidence": {
      "reviewed_by": "operator-or-truthful-assisted-review-identity",
      "rationale": "Official publication explicitly establishes applicability.",
      "verification_urls": ["https://example.edu/official-document.pdf"],
      "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "quote": "Exact supporting passage, when available."
    }
  }]
}
```

This is a **format example, not verified institutional evidence**. Replace its
values with reviewed source evidence before use. `source_id` is optional; when
present it must match the row selected by the exact `source_url`. Review identity,
rationale and verification URLs plus timezone-aware `last_verified_at` are
required when explicitly setting `vigente`, `historico` or `reemplazado`.
An old publication year does not prove that a regulation has expired.

Supported temporal fields are `temporal_status`, `document_year` (1000–9999),
`academic_period` (`YYYY-1` or `YYYY-2`), `effective_from`, `effective_to`,
`last_verified_at`, and `superseded_by` (an existing document UUID). Timestamps
must include a timezone; an effective end cannot precede its start. A replacement
cannot reference itself and is only valid for `reemplazado` status. Evidence
may additionally contain a 64-hex `source_sha256` and a bounded `quote`.

**Omitted fields preserve existing canonical values.** Explicit null clears an
optional value such as `document_year`; explicit `desconocido` changes status
intentionally. Null status is rejected. Changing a replaced source back to current
also requires explicitly clearing an existing `superseded_by`. Missing metadata
on a later reimport never overwrites a verified canonical status with unknown.
New rows retain the database's backward-compatible `desconocido` default.

### New ingestion and indexing

All three entry points accept `--temporal-manifest`:

```powershell
venv/Scripts/python.exe scripts/ingest_html.py --temporal-manifest data/sources/document_temporal_metadata.json
venv/Scripts/python.exe scripts/ingest_pdf.py --temporal-manifest data/sources/document_temporal_metadata.json
venv/Scripts/python.exe scripts/index_embeddings.py --dry-run --temporal-manifest data/sources/document_temporal_metadata.json
```

The first two commands regenerate their normal chunk outputs; use them only when
new ingestion is intended. Matching source declarations are attached as
`metadata.document_metadata`, without losing page spans, categories or other
legacy metadata. The indexer validates consistent declarations across all chunks
of a source, and persists supplied canonical fields in its existing transaction.
Manifest/chunk contradictions are rejected rather than silently overwritten.
`--check-db`, `--dry-run`, and complete-document limits retain their previous
meaning. Indexing can prune stale chunks: **never use it just to backfill status**.

### Existing indexed documents: inspect, dry-run, apply

```powershell
# Validates everything and reports database identity and intended changed fields.
venv/Scripts/python.exe scripts/backfill_document_metadata.py --manifest data/sources/document_temporal_metadata.json

# Only after reviewing the plan, database identity and source IDs:
venv/Scripts/python.exe scripts/backfill_document_metadata.py --manifest data/sources/document_temporal_metadata.json --expected-database approved_database --apply --backup C:/Backups/miuni-temporal-before.json
```

Use the database name printed by the reviewed dry-run in place of
`approved_database`. Read `DATABASE_URL` from the approved environment; do not put
credentials in command arguments, manifests or reports. Reports and backups
include only database name/server address/port, never connection credentials.

The default is dry-run. `--apply` requires the expected database name and a new
backup filename **outside every Git workspace**. The before-values JSON contains
only selected source IDs, URLs, old temporal values and the reviewed manifest;
it does not contain chunk text, embeddings, unrelated user data or credentials.
Exclusive creation prevents overwriting an older backup. The file is flushed
and fsynced before any update or transaction commit; backup failure aborts apply.
Retain this audit/rollback copy securely. It is not a full database backup or an
automatic restore command.

The updater locks exact source URLs in sorted order using the same
`pg_advisory_xact_lock(hashtextextended(source_url, 0))` identity as the indexer,
then locks and revalidates canonical rows. Unknown or duplicate source URLs,
identity/replacement mismatches and invalid merged date ranges abort the whole
plan. A single explicit transaction covers all updates; SQL/FK/check failure
rolls everything back. Reapplying identical values reports zero affected rows.
No chunk, embedding, content, document ID or source URL is rewritten or deleted.
The dry-run reports intended changes, not a durable approval or mutation receipt.

## Verified initial backfill

The 2026-11-17 six-source rollout is recorded in
[ingestion-v2 verification](ingestion-v2-verification.md). A repeated dry-run is
expected to report zero affected rows. Remaining unknown sources need separate
authoritative review; this manifest is not a whole-corpus validity declaration.

## Windows console compatibility

CLI reports use ASCII JSON escapes so accented or decomposed-Unicode source URLs
remain serializable on legacy Windows consoles. JSON parsers recover the exact
original URL; this changes neither source identity nor transaction semantics.
The subprocess regression is `python -m unittest discover -s tests -p test_backfill_console.py -v`.

## Current classification coverage

The 2026-11-21 metadata-only rollout applied 263 additional reviewed classifications:
225 current / 36 historical / 8 replaced / 219 unknown documents now remain stored. Current
retrieval has 952 eligible chunks; the total 1,379 chunk/vector rows are unchanged.
See [the complete source review](source-review-2026-11-20.md), including individual
unknown reasons and the remaining version-preserving reingestion work. Earlier
six-source counts above are historical rollout snapshots, not the current totals.
