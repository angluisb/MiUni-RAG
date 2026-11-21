# Contextual chat: measured results and remaining proof

Code adds owned conversation context, raw-query separation, deterministic saved
schedule replies, and accent-insensitive zero-hit retrieval. Tests do not establish
end-to-end answer accuracy. The real-provider sample found a retrieval instability
and exhausted provider quota on the follow-up; final integrated proof is pending.

## Real provider sample

Eight bounded sequential requests used production Python retrieval and the
configured Gemini model in process. These are real generated answers, **not**
authenticated MiUni HTTP/browser measurements. A server startup was denied before
execution; no alternative server-start operation was attempted.

| Question | Run | First text | Complete | Observation |
| --- | --- | ---: | ---: | --- |
| `Que intercambios estan disponibles?` | 1 | 10.875s | 11.900s | Mobility sources cited; no invented list of confirmed open destinations. |
| Same | 2 | 4.156s | 4.953s | Mobility sources cited; asks for program. |
| `Que documentos ocupo para mis practicas?` | 1 | 6.012s | 7.145s | Retrieved the practices regulation and cited it. |
| Same | 2 | 7.149s | 7.441s | Degree-program pages displaced the regulation; no useful document list. |
| `Que requisitos hay para titulacion?` | 1 | 4.854s | 5.440s | Program-page evidence; broad generalization is not independently verified. |
| Same | 2 | 2.763s | 3.352s | One citation label called a program page the school regulation; not clean citation proof. |
| `Quiero informacion sobre intercambios academicos` | 1 | 5.399s | 6.635s | Returned mobility information with sources. |
| `y los documentos?` with previous completed turn | 1 | — | 3.025s failure | `GoogleRateLimitError`; no successful real-provider follow-up proof. |

Seven of eight calls completed. Median first text for successes: **5.399s**;
median completion: **6.635s**. These describe this tiny sample only: no p95/p99,
production SLO, causal speedup or semantic-accuracy percentage is claimed.
Private diagnostic evidence is ignored at
`.cache/contextual-chat-real-measurement.json`; it contains synthetic conversation
content and retrieved public-source excerpts, never credentials.

## Changes prompted by measurement

HyDE could replace the original dense query with an off-topic hypothetical passage.
The first practice answer used the raw fallback; a later hypothetical query lost
the relevant regulation. Dense retrieval now retains the raw-query anchor alongside
successful HyDE, fusing both with lexical hits. Deterministic adversarial tests
cover this rule. The real-provider sample above preceded that last correction;
**it is not a benchmark of the final raw-anchor implementation**. No further
provider request was attempted after the rate limit.

Accent fallback independently changed `titulacion` from zero to eight lexical hits.
It costs about1.2s on misses without a dedicated normalized index; successful
indexed queries preserve their previous results. See `lexical-accent-search.md`.

## Proof still needed

1. With quota available, rerun the same questions against the final code and
   manually compare factual claims, citation labels and requirements to returned
   evidence. Keep unsupported open-call and program-specific claims qualified.
2. Exercise authenticated MiUni JSON/stream routes and the browser against the
   final code: reload, selected-chat isolation, delete, schedule edits and a mixed
   empty-schedule query. Server startup must be permitted by the environment.
3. Measure schedule-only HTTP latency separately; zero model calls are tested,
   but the suggested warm HTTP p95 target is not established by unit tests.

The previously reviewed 219 unknown sources remain a separate ingestion follow-up,
not silently reclassified by this feature.
