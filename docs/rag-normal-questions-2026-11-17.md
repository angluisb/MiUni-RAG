# Normal RAG questions: measured results and availability regression

The current service responds, but it cannot provide documentary answers while
every source is excluded by the enabled temporal policy. Latency improvements
must not be reported as answer-quality improvements.

## Actual requests

Six sequential streaming HTTP requests to the local Python RAG endpoint, using
the configured Gemini model: three ordinary questions, each repeated once.
Cached-model warmup/readiness completed before measurement. No map fast path,
browser, authenticated MiUni session or private academic profile was exercised.

| Question | Run | First text | Complete |
| --- | --- | ---: | ---: |
| `Para que sirve la Oficina de la Abogacia General?` | First in sample | 10.093 s | 10.384 s |
| Same | Repeated | 3.503 s | 3.956 s |
| `Que documentos ocupo para mis practicas?` | First in sample | 2.735 s | 3.134 s |
| Same | Repeated | 3.266 s | 3.613 s |
| `que intercambios estan disponibles?` | First in sample | 5.167 s | 5.485 s |
| Same | Repeated | 1.335 s | 1.710 s |

All six returned HTTP 200. Across this sample, median first text was 3.384 s and
median completion 3.784 s. These are descriptive sample medians, not production
SLOs. Six samples do not establish meaningful population p95/p99. Repetition did
not improve every question; generation output and timing varied.

All six responses lacked a concrete verified documentary answer. They disclosed
insufficient information or requested clarification. HTTP success is therefore
not evidence of documentary task success. No automatic semantic-accuracy score
was assigned.

## Verified retrieval cause

Read-only PostgreSQL checks on the intended local port 5433 confirmed:

- 488 source documents, **all `desconocido`**.
- 1,379 chunks, all with embeddings.
- The running configuration has temporal filtering enabled, whose current,
  historical and period policies exclude unknown source status.

An isolated read-only lexical comparison changed only its own settings, not the
live service or stored data. Each query was capped at eight returned chunks:

| Search term | Temporal filter enabled | Filter disabled in diagnostic only |
| --- | ---: | ---: |
| `intercambio` | 0 | 8 |
| `practicas` | 0 | 8 |
| `abogacia` | 0 | 0 |

The returned practice chunks include existing regulation/procedure sources;
exchange chunks include mobility and call documents. Their presence does **not**
verify current applicability, document dates or an open application window.
Multiple chunks can belong to one document. The `abogacia` lexical miss does not
prove absence of related vector-search results under a different policy.

This establishes a filtering/availability regression, not missing embeddings or
a reason to bulk mark all documents current. No source metadata was changed.

## Integrated-path finding

MiUni `BuildCampusQuestion` appends the complete profile, grades, weekly schedule,
catalog and current campus time before sending the question to Python
(`MiUni.Api/Controllers/ChatController.cs:231-271`). Python uses that whole string
for retrieval/HyDE. The mapper's finding was spot-checked against current source.

Consequently these raw-question timings, and the earlier direct-Python benchmark,
are **not measurements of the integrated browser/MiUni path**. Profile enlargement
and query contamination are concrete hypotheses, not measured latency causes in
this experiment. Do not claim a causal improvement over the old implementation:
there is no controlled historical-code baseline with the same eligible sources.

## Recommended order, not authorized implementation

1. Restore eligible documentary coverage through evidence-based source
   classification. Never guess validity from an old title or publication year.
   Any legacy/non-temporal compatibility rollout requires explicit authorization.
2. Surface zero eligible sources as an operational warning; a technically ready
   database/model must not be mistaken for a useful documentary corpus.
3. Keep the user's raw question separate from minimal typed private context.
   Avoid unconditional profile/kardex injection; coordinate with the proposed
   conversation-memory and personal-schedule specs.
4. Re-run a labeled factual-answer benchmark with inspected evidence, raw and
   integrated inputs, first/repeated requests, and explicit eligibility policy.
   Measure time to first text, completion, source relevance and supported claims.
5. Only then tune 30/30/8 candidates/context or reranking against quality evidence.

## Reproducibility and limits

- Ignored artifacts: `.cache/rag-normal-20261117.json` (six answers/timings),
  `.cache/rag-normal-diagnostic-20261117.json` (read-only source diagnostics),
  `.cache/integrated-local/rag.log` (retrieval/request telemetry).
- Runtime recovery: the first attempt could not reach PostgreSQL because Docker
  was stopped; it sent no Gemini requests. Docker restart briefly raced automatic
  container recovery, then the existing `miuni-postgres` became healthy. No new
  container, database, migration, classification or stored chat was created.
- Six subsequent HTTP chat requests were sent, with HyDE handled by the current
  application. Exact outgoing transport-attempt count was not instrumented; do
  not equate six chats with six billed model requests.
- This is a single local-machine sample with uncontrolled provider/load effects;
  startup is excluded. No authenticated test-user credentials were accessed.
- The previously reported four-request benchmark predates strict temporal rollout
  and must not be treated as a controlled before/after quality comparison.
