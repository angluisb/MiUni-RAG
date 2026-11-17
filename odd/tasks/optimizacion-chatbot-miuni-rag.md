# Optimización del chatbot MiUni RAG

Objetivo: reducir la latencia percibida del chatbot sin sacrificar calidad de recuperación, grounding ni el filtro temporal de la ingesta v2.
Relación: spec separado de `odd/tasks/ingesta-v2-miuni-rag.md`; se integrará mediante contratos de retrieval y metadata temporal.
Estado: integración local y migración temporal autorizadas; clasificación documental pendiente.
Branch: `feat/chatbot-optimization` (integrated in both repositories). Delivery: `ask-on-risk`; chain: `feature-branch-chain` (user selected); RDD: globally disabled by explicit request.
Forecast: 1200–1800 authored lines across pending units. Recovery mirror: pending (Engram session binding unavailable).
Runner: `venv\Scripts\python.exe`, `dotnet test`, `npm run build` cuando aplique.

## Decisión

La optimización queda separada de la ingesta porque tiene otro ciclo de medición y otro criterio de éxito. Ingesta v2 cambia la calidad y el alcance de los documentos; esta spec cambia latencia y capacidad de respuesta. Se coordinan mediante el filtro temporal y una versión explícita del pipeline.

## Ruta rápida de implementación

1. Instrumentar el flujo completo y separar retrieval de generación.
2. Enrutar preguntas de ubicación al catálogo/API, sin HyDE ni generación completa.
3. Aplicar límites de generación y streaming para reducir tiempo real y latencia percibida.
4. Medir nuevamente p50/p95 con consultas de mapa, simples y complejas antes de aceptar el resultado.

## Baseline observado

- Primera recuperación real: aproximadamente `127.7 s`.
- Carga inicial del embedding BGE-M3: aproximadamente `116 s`.
- Recuperación posterior: aproximadamente `17.0 s`.
- HyDE: hasta `15 s` por timeout/fallback.
- Embedding caliente: aproximadamente `1.8 s`.
- Búsqueda vectorial: aproximadamente `0.47 s`.
- Búsqueda léxica: aproximadamente `0.13 s`.
- El RAG usa CPU, BGE-M3, `vector_top_n=30`, `lexical_top_n=30`, `context_top_k=8` y conexiones PostgreSQL por operación.

La línea base mide principalmente retrieval; todavía debe medirse por separado el tiempo total de generación de Gemini.

### Baseline del sistema integrado

- Frontend: aproximadamente `15 ms` para entregar la aplicación.
- `GET /api/Lugar`: aproximadamente `12 ms`.
- Login: aproximadamente `472 ms`.
- Chat integrado para una consulta de ubicación: aproximadamente `52.6 s`.
- El enlace de mapa no era el cuello de botella; la consulta fallaba cuando el catálogo devolvía HTTP 500 por una migración pendiente.

## Especificaciones

### S1 — Medir el tiempo total y por etapa

El sistema debe registrar p50, p95 y p99 para:

- solicitud HTTP;
- catálogo de lugares;
- HyDE;
- embedding;
- búsqueda vectorial;
- búsqueda léxica;
- RRF;
- reranking;
- construcción del prompt;
- primer token;
- respuesta completa.

Cada medición debe indicar si fue cold start, warm start, cache hit o cache miss.

### S2 — Eliminar el cold start del primer usuario

El modelo de embeddings debe cargarse y calentarse al iniciar el servicio, antes de aceptar tráfico normal.

Criterios:

- El primer embedding real no debe cargar pesos del modelo.
- La readiness del servicio debe indicar si el modelo y PostgreSQL están listos.
- Un fallo de warmup debe producir un estado explícito, no una primera petición bloqueada durante minutos.

### S3 — Hacer HyDE opcional y acotado

HyDE no debe bloquear la recuperación durante 15 segundos.

Criterios:

- Timeout objetivo inicial: `2–3 s`.
- La búsqueda léxica debe iniciar con la pregunta original sin esperar HyDE.
- El embedding generado por HyDE puede mejorar la rama densa si llega dentro del presupuesto.
- Ante timeout, error o JSON inválido, se continúa con la pregunta original.
- El fallback conserva el filtro temporal seguro: documentos vigentes por defecto.

### S4 — Cachear resultados de alto costo

Debe existir cache con invalidación versionada para:

- HyDE por pregunta normalizada, modelo y versión del prompt;
- catálogo de lugares con TTL corto;
- embeddings de preguntas repetidas, si la memoria disponible lo permite.

No se deben cachear respuestas institucionales sin incluir la versión de documentos/pipeline en la clave.

### S5 — Reutilizar conexiones y paralelizar trabajo independiente

Criterios:

- PostgreSQL usa un pool de conexiones.
- El catálogo de lugares y retrieval se ejecutan en paralelo.
- La búsqueda vectorial y léxica siguen ejecutándose en paralelo.
- Los límites de concurrencia se configuran explícitamente para no saturar CPU, memoria ni PostgreSQL.

### S6 — Reducir trabajo de ranking sin perder calidad

Evaluar experimentalmente:

- `vector_top_n`: `30 -> 15`;
- `lexical_top_n`: `30 -> 15`;
- `context_top_k`: `8 -> 5`;
- reranking local solo cuando el benchmark demuestre una mejora de calidad suficiente.

No se acepta una reducción de latencia que aumente respuestas sin respaldo o rompa preguntas históricas/por periodo.

### S7 — Integrar filtros temporales de ingesta v2

Current authorization (verbatim): "integra las ramas para que yo pruebe, y dame preguntas y aplica las migraciones y los filtros temporalees(para que)". Local integration/application supersedes preparation-only restrictions; no remote publication or invented source classification is authorized.

El filtro temporal debe aplicarse antes de ranking y reranking.

Criterios:

- Preguntas vigentes consultan solo documentos vigentes.
- Preguntas históricas pueden consultar documentos reemplazados/históricos.
- Preguntas por periodo filtran por `academic_period`.
- Los índices de estado y periodo deben permitir que el filtro no dependa de recorrer todo JSONB.

### S8 — Streaming y experiencia percibida

Criterios:

- El endpoint streaming debe entregar el primer token tan pronto como exista contexto válido.
- El tiempo de retrieval y el tiempo de generación deben aparecer separados en métricas.
- Un usuario no debe interpretar una espera de modelo como un servidor caído.

### S9 — Enrutamiento rápido para consultas de lugares

Las preguntas de ubicación, búsqueda de lugares y navegación deben resolverse por una ruta rápida antes de invocar HyDE o la generación completa de Gemini.

Criterios:

- Detectar intenciones como "dónde está", "ubicación", "cómo llego", "qué lugares hay" y equivalentes normalizados.
- Consultar el catálogo activo mediante `/api/Lugar` o una función de dominio equivalente.
- Resolver cada lugar a su identificador canónico y construir el enlace `/mapa?lugar={id}`.
- No generar un enlace a partir del nombre escrito por el modelo ni inventar identificadores.
- Si no hay coincidencia, regresar al flujo RAG normal o mostrar una búsqueda sin resultado; no producir un enlace inválido.
- Mantener el comportamiento de categorías, coordenadas inválidas y lugares inactivos.

Objetivo inicial: consultas de mapa en `1–3 s` de extremo a extremo en warm start.

### S10 — Presupuesto de generación y respuesta progresiva

El flujo de generación debe tener un presupuesto explícito y entregar contenido progresivamente.

Criterios:

- Configurar un límite de tokens acorde con el tipo de pregunta; las respuestas de ubicación deben ser breves.
- Desactivar pensamiento extendido cuando no aporte valor a la intención detectada.
- Registrar `time_to_first_token` y `time_to_complete` por separado.
- El streaming debe conservar persistencia, cancelación y validación de la respuesta final.
- Un timeout debe devolver un error accionable y no dejar tareas asíncronas pendientes.

Objetivos iniciales: preguntas simples en `8–20 s`; preguntas complejas con RAG en `15–30 s`. Son objetivos de medición, no garantías de Gemini.

## Pronóstico de mejora

Son estimaciones para retrieval y deben validarse con benchmark; no son garantías del tiempo total de Gemini.

| Mejora | Resultado esperado |
|---|---:|
| Warmup BGE-M3 | Elimina aproximadamente 100–120 s del primer usuario |
| HyDE limitado a 2–3 s y fallback paralelo | Ahorro aproximado de 10–13 s en consultas con timeout |
| Pool PostgreSQL | Ahorro probable de 0.1–0.5 s por consulta |
| Cache de catálogo/HyDE | Ahorro de 0.1–15 s según el tipo de cache hit |
| Menos candidatos/contexto | Ahorro probable de 10–30% en ranking/prompt |
| Resultado combinado esperado | Retrieval caliente de aproximadamente 17 s a un rango objetivo de 3–8 s |
| Router de lugares | Consultas de mapa de aproximadamente 52.6 s a un objetivo de 1–3 s, evitando Gemini |
| Límite de tokens + streaming | Menor tiempo de generación y primer contenido visible en pocos segundos |

Para el primer usuario, el objetivo razonable es pasar de aproximadamente 128 s a menos de 10 s de retrieval. El tiempo total de respuesta seguirá dependiendo de Gemini, por lo que no se debe prometer un tiempo final hasta medir generación.

## Orden de implementación

- T1 — S1 — inline — métricas y benchmark reproducible — parcial: instrumentación verificada; baseline real pendiente; commit: `1d0f3bd` (305 authored changed lines).
- T2 — S2 — delegated (parallel independent unit) — warmup/readiness de embeddings — implemented in `d09983a`, independent verification pending — RED/GREEN: 5 readiness tests; isolated candidate suite passed; startup default warmup enabled; health reports model/database separately.
- T3 — S3 — HyDE con timeout y ejecución no bloqueante — complete — RED: `tests.test_rag.RetrievalTests.test_lexical_search_starts_while_hyde_is_pending` failed before implementation; GREEN: focused test and full suite pass.
- T4 — S4/S5 — delegated retrieval cache + inline catalog/pool seam — implemented in `e55c3a8`, `52e71c2`, `a1a8f0f`; independent/live DB verification pending — 12 retrieval-cache tests, catalog/pool tests; pool 4 connections/16 queued, chat capacity 4; no final-answer caching.
- T5 — S6 — tuning de candidatos y reranking — pendiente.
- T6 — S7 — inline Python + delegated isolated MiUni schema — migration applied on local5433 with backup; strict temporal filtering enabled and independently verified; all488 documents remain unclassified, so answer-quality rollout remains pending.
- T7 — S8 — inline — streaming y medición de primer token — Python instrumentation implemented; integrated MiUni persistence/cancellation and real latency pending.
- T8 — S9 — router rápido de lugares y enlaces canónicos — complete — RED: `ChatPlaceRouterTests` failed before implementation; GREEN: 5 focused tests and full MiUni suite pass. The backend fast path only answers when the question contains an exact active catalog name and a location intent; otherwise it preserves RAG.
- T9 — S10 — inline — presupuesto de generación, streaming y timeout observable — implemented in `a1a8f0f`, independent verification pending — output cap 1024, generation deadline 30s, 504 before headers, provider close on interruption; 5 focused tests passed.

## Fuera de alcance inicial

- Cambiar BGE-M3 por otro modelo antes de medir las optimizaciones de bajo riesgo.
- Reescribir PostgreSQL o reemplazar pgvector.
- Eliminar documentos históricos.
- Optimizar la interfaz visual antes de medir retrieval y generación por separado.

## Local delivery slices

No push, PR creation, merge or database migration application has been performed.
The feature tracker remains local. Each child targets its immediate predecessor:

```text
main -> feat/chatbot-optimization -> metrics -> readiness -> pool
     -> retrieval-cache -> generation -> temporal (current)
```

| Unit | Commit | Authored lines | Isolated candidate suite |
| --- | --- | ---: | --- |
| Metrics/benchmark | `1d0f3bd` | 305 | 32 run; 26 passed, 6 DB skips |
| Warmup/readiness | `d09983a` | 223 | 37 run; 31 passed, 6 DB skips |
| PostgreSQL pool | `52e71c2` | 131 | 39 run; 33 passed, 6 DB skips |
| Retrieval caches/cleanup | `e55c3a8` | 514 | 54 run; 48 passed, 6 DB skips |
| Bounded generation/catalog/map | `a1a8f0f` | 438 | 63 run; 57 passed, 6 DB skips |
| Prepared temporal filtering | `98e1e91` | 267 | 66 run; 60 passed, 6 DB skips |
| MiUni prepared schema, separate worktree | `faaeba9` | 235 | 2 EF offline tests passed; API build passed |

One honest slicing pass retained the cohesive cache and generation units with
their tests/docs. Those two exceed the approximately 400-line PR budget; any
future publication needs a maintainer-approved size exception or a new delivery
slice decision. No tests, documentation or spacing were removed to fit a budget.
Rollback boundaries are the named behavioral units above, on their local branches;
temporal SQL must remain disabled until the external schema/classification rollout.

## Log

- L1 — User request (verbatim): "Haz un spec sobre la optimizacion del chatbot o combinalo con la ingesta como lo veas mejor, yo lo veo mejor separado y dime cuanta mejora puedo esperar"
- L2 — Decision: keep chatbot optimization as a separate spec because it has an independent latency benchmark and deployment cadence, while sharing temporal-filter contracts with ingestion v2.
- L3 — Evidence: live retrieval metrics showed cold embedding load near 116 seconds, HyDE near 15 seconds, and database retrieval below 0.5 seconds per branch.
- L4 — T2 implementation: added opt-in `RAG_WARMUP_ON_STARTUP`, a `DenseEmbedder.warmup()` method, and FastAPI lifespan warmup; local `.env` enables the warmup for development. Tests keep startup warmup disabled while exercising endpoint behavior.
- L5 — T3 implementation: lexical retrieval now starts while HyDE is pending, and the default HyDE timeout is reduced from 15 seconds to 3 seconds; fallback behavior remains the original question.
- L6 — Independent verification: `compileall` passed; `unittest discover` passed with 30 tests and 6 skips; `git diff --check` passed; a timeout probe found no pending asyncio tasks. Advisory: task cleanup is runtime-probed but not yet pinned by a dedicated regression test.
- L7 — Integrated smoke verification: RAG, MiUni API, and frontend are running; login returned HTTP 200, the first cold chat exceeded the API client timeout during model startup, and a warm retry returned HTTP 200 in approximately 15.5 seconds with a generated answer. The startup warmup must complete before testing chat requests.
- L8 — Map-link incident: `/api/Lugar` returned HTTP 500 because the development database had not applied migrations `20261103160000_NegociosAmbulantes` and `20261103180000_VerificarCuentasExistentes`; the API model queried missing column `lugar.es_ambulante`. Applied both migrations, then verified `/api/Lugar` through API and Vite proxy returned HTTP 200 and `/mapa?lugar={id}` returned HTTP 200.
- L9 — User request (verbatim): "como podemos bajarlo?" followed by "haz un spec de eso". Accepted direction: prioritize a fast intent router for location questions, then generation budgets and streaming; retain full RAG for documentary and complex questions.
- L10 — T8 implementation: added `ChatPlaceRouter` and integrated it into synchronous and streaming chat. Exact active place questions now bypass RAG and return the canonical catalog name for the existing frontend map-link resolver. Full MiUni tests passed: 68 passed, 8 skipped; frontend build passed.
- L11 — Runtime verification: the failed manual test was caused by starting the API with `appsettings.Development` on port 5432, while the intended development database is on port 5433 and lacked the pulled migrations. Restarted with `ConnectionStrings__MiUniDb`, applied the three post-pull migrations, and verified synchronous and streaming location chat return HTTP 200 in under 0.1 s.

- L12 - User request (verbatim): "Hola ejecuta el spec de optimizacion del chatbot". User approved including MiUni.Api changes and preparing migrations without applying them: "si".
- L13 - Execution plan: preserve existing dirty warmup/HyDE edits; instrument and test observability first, then readiness, caches/pool and generation budgets. Temporal migration work is preparation-only. Existing T2 completion is provisional because readiness is absent. T5 defaults remain unchanged until measured quality evidence exists. Independent verification is required for shared helpers/concurrency. No project skill registry was found.

- L14 - T1 partial: added bounded per-process stage percentiles and request completion logs, separated catalog/prompt/retrieval/generation timings, and benchmark success/failure percentile summaries. RED: 3 new tests failed before implementation (missing summaries/module/logging). GREEN: 35 tests run, 29 passed, 6 PostgreSQL tests skipped. Initial sandbox run had 3 temporary-directory permission errors; approved unrestricted run passed. Live integrated baseline and percentile targets remain unverified. Risk: items 3/4 (shared sync/stream service and request-local asynchronous instrumentation).

- L15 - Independent verifier: isolated suite passed (35 run, 29 passed, 6 DB skips); baseline/candidate HTTP status/body/content-type unchanged for success, validation, empty response, provider failure and location bypass; benchmark fake-client outputs unchanged; 20 concurrent traces isolated; cancellation resets context and logs interrupted. Parent spot check: all 5 metrics tests passed; diff check passed. No live Gemini/PostgreSQL benchmark performed.
- L16 - Native review assessment: high, review_due=true (shared contracts plus pre-existing configuration); no review started or approved. Untracked selection inventory handled for assessment; provider STATUS still requires explicit intended-untracked collection. Commit deferred pending delivery chain decision because full forecast exceeds 400 authored lines. Existing dirty code is not automatically owned or staged. Recovery mirror remains pending because Engram cannot confirm host session identity.

- L17 - User decision (verbatim): "2da opcion". Selected feature-branch-chain: integrate units on feature branch before main; no publication, PR creation, merge or database application authorized. Current T1 slice: metrics module, service instrumentation, middleware, benchmark summaries, tests and measurement docs. Previous warmup/HyDE edits remain separate and unstaged.

- L18 - Metrics slice committed locally as 1d0f3bd on feat/chatbot-optimization-metrics (305 authored changed lines); parent feat/chatbot-optimization remains at the branch point. Isolated exact staged candidate: 32 tests run, 26 passed, 6 DB skips. Prior warmup/HyDE edits preserved unstaged. Native review pending; managed assets synced using the exact provider continuation. No review consent/approval claimed.
- L19 - User request (verbatim): "pues apurate a implementar lo que se te pide". Two disjoint writers launched in the same turn: T2 readiness (app initialization/readiness/tests/docs) and T4 retrieval cache/cancellation (cache/retrieval/tests/docs). Parent owns generation, catalog parallelism/cache, pool, shared settings and seam tests. Both writers observed RED/GREEN focused checks; parent generation tests observed absent limits/timeouts, serial retrieval and 502 timeout before fixes; pool tests observed missing connection API before implementation. Pipeline/ranking defaults remain unchanged.
- L20 - Integrated Python suite: 65 tests run, 59 passed, 6 PostgreSQL opt-in skips; diff check passed. Fixed test fixtures to opt out of real warmup and explicitly exercise legacy uncached behavior. New temporal tests observed missing module/filter arguments and unsafe plaintext fallback before implementation, then 3/3 passed. Admission RED missing module, then GREEN releasing capacity on cancellation. Official psycopg-pool 3.3.3 installed in project venv and pinned in requirements-rag.txt. Gemini 3 Flash minimal thinking uses supported thinking_config level; no live Gemini request made.
- L21 - MiUni prep isolated at `C:/Users/luis0/miuni-worktrees/chatbot-temporal`, branch `feat/chatbot-temporal-schema` from local main `f9eaa33`; original checkout and its router changes remain untouched. CodeGraph init succeeded there but index reads failed; bounded direct-file fallback used. Prepared document columns default unknown, restricted self-FK, status/period indexes; never infer current status or apply migrations automatically.

- L22 - User request (verbatim): "gentle-ai review mode disable, sigue". Executed exact disable command; approved retry after sandbox lock denial confirmed global off. RDD now disabled/unmanaged; do not start, retry or reactivate reviews. Existing consent was never granted; no native approval claimed.
- L23 - Required proof: six opt-in PostgreSQL TEMP-table tests were attempted; all failed ConnectionTimeout on configured loopback port5433 (no migration/document writes). Full independent verifier could not run its self-contained probes because setup failed twice; no functional PASS was produced for the current full candidate. Two EF temporal tests and API build passed in isolated MiUni worktree; migration remains unapplied.
- L24 - S9 extension: added navigation intents (map-link answer only, no invented directions) and bounded active-catalog listing. Observed RED new service test falling into RAG; then GREEN 5 campus tests. Existing documentary/mixed/ambiguous questions retain fallback. Further RDD runs are prohibited by explicit user preference.
- L25 - Final ordinary Python checks: 66 run, 60 passed, 6 DB skips. Each local commit was verified using its exact staged source in an isolated TEMP directory before commit. Provider request configuration was constructed offline with a dummy key and no network request. EF focused tests repeated after normalizing one new test-file EOF; 2/2 passed, migration commit `faaeba9` contains no application command. Existing NU1903 warning for Microsoft.OpenApi 2.3.0 remains out of scope.
- L26 - Local endpoint diagnosis used TCP only: 127.0.0.1:5432 accepts a connection; configured 127.0.0.1:5433 times out. Do not change database identity or port without user clarification. Real benchmark, quality tuning, pool/temporal integration, MiUni persistence and independent full-candidate proof remain pending; no latency or grounding-quality improvement is claimed as measured.
- L27 - User request (verbatim): "hazlo ps". Read-only diagnosis confirmed MiUni.Api development credentials work on5432, but that instance has zero source documents, no rag_chunk and no available pgvector extension. It is not an equivalent RAG database; no settings were changed. The local Docker engine was stopped. Approved local Docker Desktop startup revived the EXISTING miuni-postgres container on5433 with its existing volume/image; no container creation or migration was requested.
- L28 - Original5433 recovered: pgvector0.8.6,1379 chunks all embedded,51 active map places. Six existing PostgreSQL TEMP tests passed. Added live pool backend-reuse/rollback and temporal SQL tests restricted to pg_temp copies; full suite69/69 passed with RUN_RAG_DB_TESTS=1 in5.7s, no skips. This is verification coverage for already implemented behavior, not a new production-code change; prior RED evidence remains in implementation logs.
- L29 - Fresh independent verification authorized by resumed request and recovered environment uses a self-contained new harness, not the failed old scratch setup. Bounded actual map HTTP benchmark is being run with API_KEY empty and model hub offline, so no remote model calls/downloads are authorized. Existing migration remains prepared only and temporal rollout flag remainsfalse; full Gemini/quality and integrated persistence measurements are still pending.
- L30 - Subsequent independent Python verification passed: ten baseline/current HTTP outcomes identical, nineteen runtime probes and two durable tests passed; prompt qualifiers preserved. Added the durable probes and made TEMP column setup compatible with either pre/post-migration copies. Full Python suite71/71 passed with real PostgreSQL and no skips.
- L31 - Actual map benchmark9/9 HTTP200, canonical links valid, one catalog miss/eight hits: complete4.83-73.29ms, median6.94ms (direct Python, not integrated UI). Offline startup/readiness151.878s measured separately. Public document/chunk fingerprints unchanged. Existing benchmark children terminated.
- L32 - MiUni source seam: profile augmentation prevented a raw listing from reaching the Python fast router. In the isolated worktree, adopted the existing router/controller/test changes without editing the original checkout; observed RED3 listing/mixed-question cases and RED2 coordinate cases, then fixed raw listing, documentary fallback and map eligibility. Full isolated suite97pass/8skip; independent offline routing probes passed. Stream interruption tests assert partial delivered text but no persisted assistant. Local commits:41ba9ca (stream regression tests),a3f2407 (router fix), following prepared schemafaaeba9. No migration applied.
- L33 - User authorization (verbatim): "si", accepting "4 consultas de prueba —simples y complejas, hasta 8 llamadas contando HyDE—" with the configured `.env` API_KEY to Google Gemini. Exactly4 chats completed HTTP200 with7 guarded transport attempts (3HyDE,4generation); all generationSTOP. First-text/complete seconds: simple16.056/16.463, repeated3.407/3.622, complex4.302/6.985, repeated1.019/2.611. The last retrieval was0.183s with all input caches hit. Startup48.966s separate. Benchmark-only forced HTTPX to count the SDK's retry attempts; production unchanged. No extra model calls, migrations or stored-data changes. One additional citation domain was verified inside the exact retrieved chunks; semantic accuracy remains unevaluated. See docs/chat-optimization-validation.md and ignored .cache artifacts; do not claim population percentiles or controlled baseline improvement.

- L34 - User authorization (verbatim): "integra las ramas para que yo pruebe, y dame preguntas y aplica las migraciones y los filtros temporalees(para que)". Supersedes prior preparation-only restriction. Local integration uses feat/chatbot-optimization in both original repositories; main unchanged. MiUni original four dirty router files preserved in checkpoint3f16ec4 on backup/chatbot-pre-integration-20261116; run logs preserved. RAG fast-forwardedf0cc2f3, MiUni integrateda3f2407. No remote operation.
- L35 - All17 predecessors already applied on intended local5433; offline SQL reviewed and EF model drift check passed. Full pg_dump backup .cache/backups/pre-temporal-20261116-221320.dump (8343622bytes) preceded EF application of only20261116120000_DocumentTemporalMetadata. Pre/post488documents and1379chunks counts and content fingerprints identical (ignored proof JSON alongside backup). Local .env enables RAG_TEMPORAL_FILTER_ENABLED=true. All488documents remain desconocido; no validity/period is fabricated. Strict retrieval therefore has zero eligible institutional documents until evidence-based classification, while catalog routing remains available. Risk: item1 (stored schema), item5 (local runtime configuration). Independent verification pending. Engram mirror blocked by missing authoritative runtime identity; do not attempt writes.

- L36 - Independent postmigration verification passed: migration history, seven columns, constraints/FK/indexes, unchanged stored proof, all488unknown and zeroeligiblecurrent/historical/2025-2. Integrated MiUni dotnet test:97passed/8known opt-in skips,105total; existing Microsoft.OpenApi2.3.0 vulnerability warning unchanged. Full Python initially found one legacy fixture inheriting enabled temporal config; explicit fixture optout corrected the configuration leak, focused6/6 and independent limited1/1 passed, then final full71/71 passed with real PostgreSQL and no skips. Production temporal configuration remains true.
- L37 - Local testing services started with environment-only MiUni5433 override (no credential file changes), development admin seed disabled, cached embedding warmup offline. Frontend localhost5173 HTTP200; API localhost5124/api/Lugar HTTP200; RAG localhost8000/health/ready HTTP200 with model/database ready. No new Gemini chat requests. Owned verifier scratch removed; backups and private logs retained under ignored .cache. Risk: item1 (schema), item5 (runtime configuration); independent verification passed.
