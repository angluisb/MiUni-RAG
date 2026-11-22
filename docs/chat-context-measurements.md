# Contextual chat: measured results and remaining proof

## Latest post-refresh retest (2026-11-22)

Five paced real-provider calls exercised the production Python retrieval and
streaming-generation path after refreshing the eligible sources. They did not
start the application server or test authenticated HTTP/browser behavior.

| Question | First text | Complete | Observed result |
| --- | ---: | ---: | --- |
| `Que documentos ocupo para mis practicas?` | 5.952s | 7.100s | Practices regulation cited; asks for the program for specifics. |
| Same | 3.722s | 5.433s | Regulation and requirements retained. |
| `Que requisitos hay para titulacion?` | 2.986s | 3.551s | General requirements and program-specific caveat. |
| `Quiero informacion sobre intercambios academicos` | 3.046s | 4.166s | Mobility sources retrieved. |
| `y los documentos?` with the completed exchange turn | 2.709s | 3.900s | Follow-up retained the exchange context and mobility sources. |

Median first text: **3.046s**; median completion: **4.166s**. This is a five-call
sample, not a production SLO or semantic-accuracy measurement. The prior report
was preserved at `.cache/contextual-chat-before-retest-20261122T063523Z.json`;
the latest evidence is `.cache/contextual-chat-final-measurement.json`.

Correction to the preceding status message: **HyDE fell back in 4/5 calls**, not
3/5. The failed attempts returned in 1.20–1.62s against a 3s configured timeout,
so those observations were not timeout failures. The broad exception handler
logs only a generic warning, so the provider exception type/status was not
captured. One isolated call using the same 3s budget succeeded in 2.824s; this
shows latency near the budget but does not identify the earlier errors. Safe
exception diagnostics are needed before changing retries or timeouts.

## Prior final-code check (before the source refresh)

A new availability probe succeeded, then five paced real-provider answers on the
final contextual/raw-anchor code all completed. No prior report was overwritten.

| Question | First text | Complete | Observed result |
| --- | ---: | ---: | --- |
| `Que documentos ocupo para mis practicas?` | 5.466s | 6.674s | Practices regulation retrieved and cited. |
| Same | 3.207s | 4.409s | Same regulation retained; source-specific documents and career caveat. |
| `Que requisitos hay para titulacion?` | 3.908s | 4.534s | Program pages cited; institution-wide generalization still requires care. |
| `Quiero informacion sobre intercambios academicos` | 2.711s | 4.020s | Mobility information with documentary sources. |
| `y los documentos?` with that completed turn | 3.160s | 4.235s | Kept the exchange topic and retrieved international/national mobility requirements. |

Median first text: **3.207s**; median complete: **4.409s**. Deliberate ten-second
inter-request pacing is excluded. Five answers are not a production benchmark or
semantic-accuracy percentage, and the two practice answers do not prove universal
stability. Four HyDE attempts fell back safely; the successful hypothetical query
still retained the raw anchor. Evidence remains private/ignored at
`.cache/contextual-chat-final-measurement.json`.

This closes the previously unavailable real-provider follow-up check, not the
authenticated HTTP/browser acceptance. No server-start denial was bypassed.
The historical sample and its failures below are retained for comparison, not
treated as a controlled speedup experiment. This sample precedes the separate
150-source refresh and any future metadata promotions from that batch.

## Previous sample and limitations

Code adds owned conversation context, raw-query separation, deterministic saved
schedule replies, and accent-insensitive zero-hit retrieval. Tests do not establish
end-to-end answer accuracy. The real-provider sample found a retrieval instability
and exhausted provider quota on that earlier follow-up. The latest five-answer
run above closes that provider check; authenticated HTTP/browser proof is pending.

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
provider request was attempted again within that sampling run. A later user-
authorized availability probe and paced five-answer run are recorded above.

Accent fallback independently changed `titulacion` from zero to eight lexical hits.
It costs about1.2s on misses without a dedicated normalized index; successful
indexed queries preserve their previous results. See `lexical-accent-search.md`.

## Proof still needed

1. The latest final-code sample above has been compared qualitatively with its
   retrieved sources: both practice answers retain the regulation and the real
   follow-up retains mobility context. This is not a full factual-accuracy audit;
   unsupported open-call and institution-wide/program-specific claims still need
   qualification. Extend coverage when evaluating any later source promotions.
2. Exercise authenticated MiUni JSON/stream routes and the browser against the
   final code: reload, selected-chat isolation, delete, schedule edits and a mixed
   empty-schedule query. Server startup must be permitted by the environment.
3. Measure schedule-only HTTP latency separately; zero model calls are tested,
   but the suggested warm HTTP p95 target is not established by unit tests.

The previously reviewed 219 unknown sources remain a separate ingestion follow-up,
not silently reclassified by this feature.
