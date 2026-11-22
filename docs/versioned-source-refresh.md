# Refresh sources without losing their previous copy

Use opt-in version archives when replacing an existing canonical source. The indexer
captures its complete document row and every associated/URL-matched chunk row,
including vector text, IDs, timestamps, metadata and generated search text, before
any model call or database mutation. Existing indexing without these options is unchanged.

## Quick path

1. Back up the intended database and review the complete-source input JSONL.
2. Prepare a guard manifest from the reviewed database identities:

   ```json
   {"version": 1, "sources": [{"source_url": "https://example.edu/source", "source_id": "00000000-0000-0000-0000-000000000001", "temporal_status": "desconocido"}]}
   ```

3. Validate without database/model/archive writes:

   ```powershell
   venv/Scripts/python.exe scripts/index_embeddings.py --input refreshed.jsonl --version-archive-dir "$env:LOCALAPPDATA/MiUni/source-versions" --refresh-guard guards.json --dry-run
   ```

4. After validating the intended database, backup and selected sources, use the same
   command without `--dry-run` to apply. Each selected complete document must have
   exactly one guard entry. Duplicate/malformed entries fail; extra valid entries
   are permitted for `--limit-documents` previews. Dry-run validates manifest/input
   shape, not current database identity; actual apply checks identity/status under lock.

## Preservation and failure behavior

- The archive directory must be absolute and outside this repository, including
  symlink-resolved paths. Use a local durable filesystem with atomic hard-link support.
- Source advisory locking and document/chunk row locks cover validation and capture.
  The canonical URL must resolve to exactly one existing document. UUID/status
  mismatches abort before archive creation, model calls or database changes.
- Archives are canonical UTF-8 JSON named by their SHA-256, atomically published
  without replacement after file flush/fsync. Existing files are hash-checked;
  corruption, unsupported linking or I/O failures abort before SQL mutations.
  POSIX additionally fsyncs the directory; Windows fsyncs the final linked file.
- An archive contains schema version, database identity (not credentials), exact
  source identity, complete old rows, chunk count and a separate preimage hash.
  Read it with `app.rag.version_archive.read_archive(path)` to verify both hashes
  and source/count consistency before offline inspection or a separately reviewed recovery.
- A preimage can remain when subsequent embedding, SQL or commit fails. It is NOT
  a commit receipt, an automatic restore operation, or historical retrieval support.
  No archive work occurs after database commit, so archive errors cannot falsely
  report failure after a successful commit.
- Existing embedding cache checks (hash, model, dimension and pipeline), canonical
  temporal metadata handling, URL/UUID identities and stale-chunk pruning are reused.
  Fetch time alone never establishes a source's temporal classification.

## Verification

`tests/test_version_archive.py` uses external temporary archive directories and
isolated PostgreSQL TEMP tables when `RUN_RAG_DB_TESTS=1`; it never edits live rows.
Keep operational archives outside Git and retain database backups independently.

## Completed local batch

The 118 prepared documents were indexed with the archive and identity/status guards enabled. A fresh custom-format database dump was validated before apply. Post-apply checks found 118 readable preimage archives, unchanged full-row hashes for all 370 untouched sources, 118 refreshed chunk sets matching the prepared inputs, and 1024-dimensional non-null embeddings. Totals are 488 documents and 1380 chunks; temporal status counts remain 225 `vigente`, 36 `historico`, 8 `reemplazado`, and 219 `desconocido`. No schema migration or status promotion was performed.
