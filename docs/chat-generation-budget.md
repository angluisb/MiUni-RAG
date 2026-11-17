# Bounded chat generation

Chat now overlaps active-place catalog loading with documentary retrieval. Both
branches are cancelled and awaited on failure or client cancellation. A blocked
SQL/inference thread cannot be forcibly stopped by asyncio; PostgreSQL statement
timeouts and the existing serialized embedding model remain the safety bounds.

## Configuration

| Setting | Default | Effect |
| --- | --- | --- |
| `LLM_MAX_OUTPUT_TOKENS` | 1024 | Output-token budget for model calls, including HyDE |
| `LLM_GENERATION_TIMEOUT_SECONDS` | 30 | Total final-generation budget, separate from retrieval |
| `LLM_THINKING_LEVEL` | minimal | Thinking level for the supported Gemini 3 Flash families |
| `CHAT_MAX_CONCURRENT_REQUESTS` | 4 | Active HTTP chats per process, including open streams |
| `CHAT_QUEUE_TIMEOUT_SECONDS` | 2 | Capacity acquisition wait, then 503 with Retry-After |
| `RAG_CATALOG_CACHE_TTL_SECONDS` | 15 | Active-place catalog freshness bound |
| `RAG_CACHE_MAX_ENTRIES` | 128 | Per-cache maximum; zero disables caching |
| `RAG_DB_POOL_ENABLED` | true | Reuse PostgreSQL connections for repository operations |
| `RAG_DB_POOL_MAX_SIZE` | 4 | Maximum connections per process |
| `RAG_DB_POOL_MAX_WAITING` | 16 | Maximum queued connection requests per pool |
| `RAG_DB_POOL_TIMEOUT_SECONDS` | 5 | Maximum pool acquisition wait |

Install `requirements-rag.txt` to obtain the official Psycopg pool. Its transaction
context commits or rolls back before returning a connection. Application shutdown
closes the retriever pool. The public `connect()` raw-connection API and explicit
subclass overrides remain available for isolated indexing/integration tests.

Place-only matches retain the deterministic canonical map answer and do not call
Gemini. This includes "cómo llego/llegar a" matched destinations (a map link, not
invented turn-by-turn directions) and "qué lugares hay" (up to ten active catalog
entries with canonical links and an explicit displayed/total count). Unknown or
ambiguous destinations and mixed documentary questions keep the RAG fallback.
Other questions share the configurable output budget; the default ranking
and context sizes are unchanged pending a quality benchmark. Successful HyDE and
embedding values are versioned and cached, never complete institutional answers.
Catalog entries use repository identity and pipeline version, expire after the
short TTL, and are fetched again after pipeline changes. No stale-on-error fallback
is used. Cache hits do not bypass fresh vector or lexical document searches.

The generation deadline is shared across all stream chunks, not restarted per
chunk. Closing or timing out the consumer closes the provider iterator. Before
HTTP headers, timeouts return 504 with an instruction to try a shorter question.
After streaming starts, failures abort the stream rather than append a fabricated
success message; the caller must treat interruption as an incomplete answer.
MiUni persistence/cancellation still needs integrated runtime verification.

The supported Gemini 3 Flash models use `thinking_config.thinking_level`, not a
zero-token budget. Other model families keep their provider thinking defaults.
Transport retries are disabled so hidden retries cannot multiply the budget.
References: [Gemini thinking](https://ai.google.dev/gemini-api/docs/thinking),
[LangChain integration](https://github.com/langchain-ai/langchain-google),
[Psycopg pooling](https://www.psycopg.org/psycopg3/docs/advanced/pool.html).

These limits improve boundedness, not a measured latency guarantee. Run the real
benchmark for map, simple and complex questions before accepting the spec targets.
