# Chat optimization: observed validation

The recovered local RAG service completed every authorized test request. Map
responses were measured separately from real Gemini answers; neither benchmark
is a controlled before/after comparison or an integrated browser measurement.

## Historical measurement snapshot

This report describes measurements before the authorized temporal migration/strict
rollout. For current normal-question results and the zero-eligible-source finding,
see [the 2026-11-17 diagnostic](rag-normal-questions-2026-11-17.md). The old pending
rollout statements below are historical, not the current deployment state.

## Real Gemini requests

Model: `gemini-3.1-flash-lite`; output ceiling: 1024 tokens; generation deadline:
30 seconds. Two questions were each repeated once, for exactly four HTTP chats.
The user authorized at most eight model calls including HyDE.

| Request | First text | Complete | Retrieval |
| --- | ---: | ---: | ---: |
| Simple, first after warmup | 16.056 s | 16.463 s | 12.918 s |
| Simple, repeated | 3.407 s | 3.622 s | 2.159 s |
| Complex, first | 4.302 s | 6.985 s | 2.715 s |
| Complex, repeated | 1.019 s | 2.611 s | 0.183 s |

All four requests returned HTTP 200. All four generation streams ended with
`STOP`; reported output tokens were 126, 102, 832 and 620. The first HyDE timed
out and was cancelled; fallback continued. Seven actual outgoing requests were
counted before transport: three HyDE attempts and four final generations. No
extra chat, model-list probe or benchmark rerun consumed the remaining budget.

The last request hit catalog, HyDE and embedding caches but generated a **fresh**
answer. The first simple request still spent 9.538 seconds on its query embedding;
startup warmup does not imply that every CPU/client cache is already warm.

Method caveat: the installed SDK has an internal aiohttp retry within its
once-request method. Only the benchmark child was forced to HTTPX, with a hard
pre-send cap and allowed-host guard, to enforce the eight-request authorization.
Production code/configuration was not changed for that transport choice.
Hugging Face was offline, telemetry was disabled, and the configured API key was
never written to artifacts or printed. Parent artifact scanning passed.

Source URLs were captured for all four responses. One additional citation domain
was absent from the source-URL list but **was found inside the eight exact retrieved
chunks** in a subsequent read-only audit. This is provenance evidence, not a
semantic-accuracy evaluation. No answer-quality score or grounding improvement is
claimed from these four examples.

Artifacts, ignored by Git:
- `.cache/chat-gemini-benchmark.json`
- `.cache/chat-gemini-benchmark.log`
- `.cache/chat-gemini-budget.json`

## Map paths without generation

Nine real Python HTTP requests used the existing 51-place catalog: direct
location, navigation and listing, three repetitions each. Every response returned
200 and used canonical catalog identities. The listing contained ten links.

Complete times ranged from **4.83 to 73.29 ms**, median **6.94 ms**. Telemetry
contained only catalog/HTTP stages: one catalog miss and eight hits, without
retrieval or generation. These are direct Python results, not browser/.NET totals.

Offline model startup/readiness took 151.878 seconds in the map run and 48.966
seconds in the subsequent Gemini run. Startup time is excluded from the HTTP
table and remains a separate operational cost. These tiny sequential samples do
not establish reliable population p95/p99, throughput or a production SLO.

Artifacts: `.cache/chat-map-recovered.json` and `.cache/chat-map-recovered.log`.

## Functional and safety checks

- Python: **71/71 passed**, including all PostgreSQL tests, pool backend reuse and
  rollback, and temporal filtering on `pg_temp` copies. No public migration ran.
- Independent Python probes: ten baseline HTTP outcomes matched exactly; nineteen
  runtime assertions and two durable regression tests passed. Grounding prompt
  qualifiers were preserved.
- Original MiUni checkout: **88 passed, 8 skipped**, using in-memory/fake-provider
  tests. The original dirty checkout was not edited.
- Isolated MiUni worktree after fixes: **97 passed, 8 skipped**. Coverage includes
  partial-stream cancellation/interruption without assistant persistence, raw
  catalog routing before profile augmentation, documentary fallback and invalid
  coordinate exclusion. Skipped tests require separate PostgreSQL/auth opt-ins.
- Independent offline .NET probes preserved five prior routing outcomes and
  verified bounded listings, mixed-question fallback and unchanged input/source
  hashes. Its SDK first-run printed a development-certificate setup message; no
  trust/removal command ran, and whether a certificate was newly created was not
  determined.
- Public database fingerprints matched before and after both runtime benchmarks:
  488 source documents and 1379 embedded chunks. No existing stored data changed.
- Benchmark child processes were terminated. The recovered original Docker
  database remains available on its original port 5433; no port/credential was
  changed, no container created, and the unrelated 5432 database was not modified.

## Still pending

Candidate/context tuning remains 30/30/8 until a labeled quality experiment can
justify 15/15/5 or reranking. Temporal rollout remains disabled pending separately
authorized migration application and explicit document classification. Browser
end-to-end latency and live authenticated MiUni persistence are not established
by the direct Python timings or in-memory .NET tests. Reviews remain globally
disabled at the user's request; no approval or publication is implied.
