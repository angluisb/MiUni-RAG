# PostgreSQL connection reuse

Repository operations use the official `psycopg-pool` dependency pinned in
`requirements-rag.txt`. Install that file in the project environment before running
RAG with pooling enabled.

The defaults are four connections, sixteen queued requests, and a five-second
acquisition timeout per process. Configure `RAG_DB_POOL_ENABLED`,
`RAG_DB_POOL_MAX_SIZE`, `RAG_DB_POOL_MAX_WAITING`, and
`RAG_DB_POOL_TIMEOUT_SECONDS`. Connection and SQL statement timeouts remain active.

Each operation returns its connection through the pool transaction context, which
commits on success and rolls back on failure. Shutdown closes the cached retriever
and its pool. No database is created, migrated, or selected automatically.

The public raw `connect()` method and explicit overrides remain compatible with
isolated TEMP-table indexing tests. Disable pooling to exercise the previous
connection-per-operation path. Pool configuration/fake-connection tests pass;
real integration is pending availability of the configured PostgreSQL endpoint.
