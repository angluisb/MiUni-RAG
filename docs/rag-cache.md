# Bounded retrieval caches

Repeated questions reuse successful HyDE text and embeddings, not retrieved
chunks or generated answers. Vector and lexical searches still run on every
request, so these caches do not freeze document or temporal-filter results.

## Configuration

| Setting | Default | Effect |
| --- | --- | --- |
| `RAG_CACHE_MAX_ENTRIES` | `128` | Maximum entries per cache; `0` disables storage. |
| `RAG_HYDE_CACHE_TTL_SECONDS` | `120` | Fixed HyDE entry lifetime. |
| `RAG_EMBEDDING_CACHE_TTL_SECONDS` | `600` | Fixed embedding entry lifetime. |
| `RAG_HYDE_PROMPT_VERSION` | `hyde-v1` | Change when the HyDE prompt changes. |

Caches belong to a retrieval service instance and are process-local; replicas
do not share them. Entries expire using a monotonic clock. Least-recently-used
eviction bounds memory by entry count, not bytes. Thread-safe operations protect
the cache structure; callers must not mutate cached values. Concurrent misses
may compute the same value independently; there is no single-flight lock.

## Invalidation and failure behavior

HyDE keys include the normalized question, LLM model, embedding pipeline version,
HyDE prompt version and requested sentence count. Embedding keys include the
normalized dense input, embedding model and pipeline version. Normalization uses
Unicode NFC, case folding and whitespace folding; it does not remove accents,
periods, digits or word boundaries. Misses still send the original text to the
model; lexical retrieval always receives the original question.

Change `RAG_EMBEDDING_PIPELINE_VERSION` when embedding preprocessing changes.
Change `RAG_HYDE_PROMPT_VERSION` when prompt semantics change. Each cache exposes
`clear()` for explicit in-process invalidation. TTL remains fixed from insertion;
hits update LRU order without extending the lifetime.

HyDE timeout, provider errors, empty text and non-string results are not cached.
Embedding failures are not cached. Per-request retrieval metrics report
`hyde_cache` and `embedding_cache` as `hit`, `miss` or `disabled`; absent/disabled
HyDE reports `disabled`. Embedding hits leave `embedding_ms` at zero;
`hyde_ms` includes the inexpensive cache lookup on a HyDE hit.

Cancellation or branch failure cancels and awaits created asyncio tasks.
Cancelling an `asyncio.to_thread` awaiter does **not** terminate its SQL or model
thread. PostgreSQL statement timeouts still bound outstanding database work;
this cleanup must not be interpreted as physical query cancellation.

## Verify without external services

```powershell
venv/Scripts/python.exe -m unittest discover -s tests -p test_retrieval_cache.py -v
venv/Scripts/python.exe -m unittest discover -s tests -p test_rag.py -v
```

The focused suite uses fake clocks, repositories and model calls. It covers
versioned hits, normalization boundaries, expiry/eviction, disabled caches,
failure fallback, original lexical input and asynchronous sibling cleanup.
