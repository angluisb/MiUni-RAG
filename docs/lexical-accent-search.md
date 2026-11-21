# Accent-insensitive lexical misses

`RagRepository.lexical_search` keeps the existing Spanish full-text index query
first. Only zero results trigger accent-insensitive matching. Successful indexed
hits retain their IDs, scores, ordering, and limit without another query.

## Matching and safety

- The fallback folds acute-accented vowels and `ü` in both content and question;
  `ñ` remains distinct. Decomposed question input is normalized to NFC only for
  the fallback. Stored content and returned text are not rewritten.
- Both paths use Spanish `websearch_to_tsquery`, parameterized questions,
  `score DESC, id`, and the requested candidate limit.
- The exact existing temporal predicate and parameters apply before fallback
  vector generation. Historical, replaced, unknown, and expired documents remain
  excluded by the default current-document intent. Explicit historical and
  period-specific intents retain their existing rules.
- Matching remains content-only: the live generated `search_tsv` expression is
  `to_tsvector('spanish', coalesce(content, ''))`. Titles are not newly searchable.
- No extension, persistent schema/index change, embedding, or corpus mutation is
  required. Materialized CTEs filter eligible documents first and calculate each
  folded vector once; they require PostgreSQL 12 or later.

## Measured cost and limitations

The fallback is a scan, **not an indexed accent-insensitive search**. The candidate
limit bounds returned rows, not scanned content or CPU work. On the local
1,379-chunk corpus, the original `titulacion` query returned zero; fallback returned
eight. Original `titulación`, `becas`, and `calendario` results retained exact IDs
and scores in before/after differential probes.

After temporal-first materialization, a warm `titulacion` request took 1,187.94 ms;
two unmatched requests took 1,097.19 and 1,138.89 ms. One read-only
`EXPLAIN ANALYZE` reported 1,320.874 ms. Successful indexed queries typically took
approximately 5–22 ms warm in the earlier probe. These small local samples are
not p95 estimates or production performance guarantees. The accepted tradeoff
prioritizes recall correctness on zero-hit searches over this material latency;
it is not a latency improvement. A folded-vector index remains a follow-up
optimization requiring separate schema authorization.

Translating `search_tsv::text` instead is not equivalent: Spanish stemming maps
`titulación` to `titul`, but `titulacion` to `titulacion`. Accent removal after
stemming cannot recover suffixes already removed. A durable folded-vector index
could avoid repeated tokenization, but that schema decision is outside this
change's authorized scope. Non-NFC content is not rewritten or generalized here.

## Verification

```powershell
$env:RUN_RAG_DB_TESTS = '1'
venv/Scripts/python.exe -m unittest discover -s tests -p test_lexical_accents.py -v
venv/Scripts/python.exe -m unittest discover -s tests -p test_temporal_postgres.py -v
```

The accent tests cover SQL parameterization and zero-hit gating, plus PostgreSQL
TEMP-table semantic probes for accents, decomposed queries, diaeresis, distinct
`ñ`, limits, temporal exclusion, period selection, title exclusion, and preservation
of successful indexed ranking. TEMP objects disappear when their connection closes;
the probes do not write public corpus rows. Local measurement evidence is ignored
under `.cache/lexical-accent-fix/`.
