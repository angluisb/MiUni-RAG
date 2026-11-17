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
remains false for deployments without the migration. All 488 documents initially
have `desconocido`, with no verified temporal metadata. Consequently, strict
retrieval currently finds **no eligible institutional documents**. This is a safe
rollout restriction, not evidence that documents were lost. Catalog/map routing
is independent. Classify sources only from verified status, dates and periods;
do not bulk mark them current to make a demonstration answer work.

Use current, historical and explicit-period questions to check that unsupported
claims are not invented. Meaningful answer-quality comparisons require verified
source classifications first. The prior four Gemini measurements predate this
strict rollout and must not be described as its quality benchmark.
