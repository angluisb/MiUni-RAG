# MiUni RAG Ingestion v2

Objective: define the implementation contract for compliant web ingestion, temporal document retrieval, and RAG/MiUni integration.
Branch: feat/ingestion-v2. Delivery: ask-on-risk; reuse the previously selected feature-branch-chain strategy for local work units; no push/PR authorized. Forecast: 800-1400 authored lines across two cohesive behaviors and verification.
Test runner: Python `venv\Scripts\python.exe -m unittest`; RUN_RAG_DB_TESTS=1 for isolated PostgreSQL TEMP tests. Existing MiUni schema already applied; no new migration planned. Engram mirror pending: host runtime identity unavailable.

## Specs

### S1 — Validate the current integrated baseline
Authorized scope: verify that MiUni and `rag-miuni` build/start together without changing source code.
Acceptance criteria:
- The RAG service starts at `http://127.0.0.1:8000`.
- The MiUni API starts through `scripts/dev.ps1 -Action api` at `http://127.0.0.1:5124`.
- The shared PostgreSQL/RAG configuration and required migrations are documented as prerequisites.
- Build and focused endpoint checks record their observed result.

### S2 — Respect robots.txt during ingestion
Authorized scope: make every crawler read and enforce the applicable `robots.txt` policy before downloading HTML or PDF resources.
Acceptance criteria:
- Policies are resolved per host and cached with a bounded refresh policy.
- Disallowed URLs are not requested.
- Crawl delay, when declared and supported, is respected.
- The ingest report records allowed, rejected, and unavailable-policy outcomes.

### S3 — Capture temporal document metadata
Authorized scope: attach document-level temporal metadata to newly ingested and already indexed documents.
Acceptance criteria:
- Metadata supports `temporal_status` with at least `vigente`, `reemplazado`, `historico`, and `desconocido`.
- Metadata can represent `document_year`, `academic_period`, `effective_from`, `effective_to`, `last_verified_at`, and `superseded_by` when known.
- Existing documents receive a backward-compatible default and are not deleted.
- The canonical status is not represented only by a boolean `vigente` field.

### S4 — Filter retrieval without deleting historical documents
Authorized scope: apply temporal policy in vector and lexical retrieval.
Acceptance criteria:
- Default questions retrieve only documents with current/valid status.
- Historical questions can retrieve historical and replaced documents.
- A specific period such as `2025-2` filters by `academic_period`.
- Unknown temporal status is excluded from default current answers unless an explicit fallback policy is selected.
- Documents remain stored for audit and historical answers.

### S5 — Structured temporal intent from HyDE
Authorized scope: extend the HyDE request/response contract with validated temporal intent.
Acceptance criteria:
- The model output has this shape:
  `{ "alcance_temporal": "vigente | historico | periodo_especifico", "periodo": "2025-2", "hyde_doc": "..." }`
- Invalid or unavailable model output falls back safely to current-document retrieval.
- Retrieval uses `hyde_doc` for dense search and the original question for lexical search.
- The temporal filter is applied before candidate ranking/reranking.

### S6 — Preserve compatibility with MiUni
Authorized scope: evolve the shared MiUni schema and Python repository contract without creating a parallel RAG database.
Acceptance criteria:
- Changes remain compatible with `documentofuente` and `rag_chunk`.
- Migration ownership remains in `MiUni.Api`.
- Existing ingestion, search, and chat behavior remains covered by regression tests.
- No source code is changed until the schema and migration design is approved.

## Tasks

- T1 — S1 — inline — complete — fresh RAG/API HTTP200 and API51places; exact dev.ps1 startup observed; evidence in docs/ingestion-v2-verification.md.
- T2 — S2 — delegated parallel independent writer — complete — commit9f8f3cf; focused13+7, parentseam110/110, independentnetwork/reportprobes passed. Risk:item2.
- T3 — S3/S6 — delegated parallel independent writer — complete — commitffca012; focused7+9 andexistingPG6+2; canonical persistence/backfill validated independently. Risk:items1/3/4.
- T4 — S4/S5 — inline reconciliation — complete — prior98e1e91/MiUnifaaeba9 reused; independentSQL/structuredintent and livecurrent/history/periodcoverage verified; no reimplementation.
- T5 — S1/S6 — inline plus independent verifier — complete —110tests/77independentassertions/twoHTTPbaselinechecks/twoactualanswers; no blocker. Final verification record accompanies closure commit.

- T6 — S3/S4/S6 — inline — complete first reviewed batch — six-row canonical update fromffca012 manifest, full+before-values backups, independent live recheck; current14chunks, unchanged488docs/1379chunks;482sourcesremainunknown. Risk:item1.

## Log

- L1 — User request (verbatim): "ingesta v2 -mi uni RAG\n\nleer el robots.txt para respetar a la uni.\nconseguir los documentos y poner en su metadata su ano crear, maybe un estado que sea\nvigente: boolean\ny filtrar por ese estado o elimianar los documentos que ya descargamos y que\nvigente == False;\ny desde el pipeline ajustar\n**no se eliminan documentos se filtra co la query a menos que la pregunta sea de\ncaracter historico, esto se puede saber aprovechando que llamamos a gemini\npara HyDE en la misma consulta le mandamos esto:\n{\n  \"alcance_temporal\": \"vigente | historico | periodo_especifico\",\n  \"periodo\": \"2025-2\",\n  \"hyde_doc\": \"...\"\n}\nlos documentos actuales tambien deben de tener el estado hay que platicar como seria mejor implementarlo y que campo seria no necesariamente el boolean y ver como mejorar los tiempos de respuesta del chatbot"
- L2 — Current verification: MiUni fetched and fast-forwarded from `8623f23` to `8c05454`; six commits were behind before the update. RAG had no remote divergence.
- L3 — Current runtime check: RAG `/docs` returned 200; MiUni API started through `scripts/dev.ps1 -Action api` at `http://localhost:5124`.
- L4 — Planning decision: retain historical documents and filter at retrieval time; model temporal status explicitly rather than using only `vigente: boolean`.
- L5 — Scope correction: chatbot latency measurement and optimization belong exclusively to `odd/tasks/optimizacion-chatbot-miuni-rag.md`; this spec keeps only ingestion and temporal-retrieval requirements.

- L6 - User authorization (verbatim): "okay, empieza con el spec de ingesta o si crees quese desbia un poco haz otro y ejecutalo". Execute this existing spec: it directly covers robots, missing canonical temporal persistence and source classification; no separate feature spec needed. Prior no-source-write planning restriction is superseded by explicit implementation authorization. Canonical schema design and migration were already approved/applied in the optimization session.
- L7 - Current evidence:488documents allunknown/1379embedded chunks; strict temporal filter returns no eligible sources. Existing indexer writes temporal values only to neither canonical columns nor a validated envelope. Existing crawler allowlists are checked after automatic redirects. Preserve dirty prompt fix/earlier specs, unrelated untracked files and containers. Branch created without resetting/stashing work; commit only ingestion-owned paths. Reviews remain explicitly disabled.
- L8 - Routing: two independent multi-file behaviors with disjoint surfaces run as bounded parallel writers (robots vs manifest/persistence); source-evidence curation is a separate read-only bounded map for parent-controlled live backfill. Parent owns Git, task file, final manifests and actual DB updates. Reuse existing per-source advisory lock/indexer vector-reuse invariants; never backfill by reindexing because it prunes stale chunks.

- L9 - Source review: independently verified exact current2020practices regulation link from DAE, with live/raw/metadata SHA256 equality; current Buddy substantive content matches indexed/raw/live normalized text. Explicit2020abrogation proves2017link-page replaced; official closed markers/deadlines support three historical mobility calls, including future mobility periods whose application windows are closed. Unknown years/effective dates remain unknown; no source classified from URL/year/HTTP200 alone. Curated six-row candidate manifest staged only under ignored.cache pending writer format validation and independent checks.
- L10 - Full private backup pre-ingestion-v2-20261117-122640.dump8347177bytes created before any metadata change. Preproof488unknown documents/1379chunks hashes recorded. Venv lacked BeautifulSoup/pypdf despite existing pins; native-approved install added beautifulsoup4=4.14.2,pypdf=6.19.0 and soupsieve4.1.1, no requirements edits. Robots404/410absence policy explicitly allows public resources;5xx/network/401/403/429remain blocked (RFC9309sections2.3.1.3/4).

- L11 - T1fresh baseline: RAGhealth/ready200(modelready/PostgreSQLready) and MiUni API/api/Lugar200/51places; APIstartedthrough exactscripts/dev.ps1 -Action api withenvironment5433 and no seeds/migrations. WriterT2focused13+7pass; T3focused7+9andexistingPG6+2pass. Parentseam110/110pass(noDBskips), pipcheckpass. Sixcuratedmanifestrecords validate and publicbackfilldryrun matched6/affected6/noDML.
- L12 - Independentfeatureverification77assertions+twoHTTPchecks passed perS1-S6; no blocker. Testscoverednetworkguards/URLnormalization/redirects/reports/TTL/delay, sourceprovenance/omissions/nulls/identities, atomicrollback/backup/unchangedchunkshashes, canonicaltemporalbranches andbaselineCLIparity. Existingwriterregressions alreadyrepresentcriticalindependentprobes; no duplicate testsadded. Nativegentlereview remainsdisabled; no fabricatedreviewapproval.
- L13 - Localworkunits naturally exceed400advisorylines because sharedguard+bothconsumers and typedmetadata+atomicbackfill each needtheirtests/docs together; do notminifyoromitverification. Preservebestcohesiveunits; recommend PRsizeexceptionoronehonestfuturePRslicingpass ifpublishing. Previouslyselectedfeature-branch-chain retained; no push/PRauthorized.

- L14 - Applied reviewed6canonicalmetadata rows only after fullbackup/dryrun/independent77checks. OutsideGitbefore-valuesbackup under localprofileMiUni/backups created andfsynced first. Independentlyrechecked final2vigente/3historico/1reemplazado/482desconocido and6manifestidentities; canonicalcoveragecurrent14chunks2docs,historical27chunks6docs,2027-1period9chunks2docs. Non-temporaldocandfullchunkhashes match prestate exactly; count488/1379 unchanged.
- L15 - Two native-consented real Gemini streaming smokes returned200 and8retrievedchunkseach: practices firsttext5.161s/complete6.306s;Buddy5.567s/6.325s. Medical-service certificate and activity-report facts were confirmed in exactselectedpracticechunks; officialregulation/program links supplied. This proves restored source access, not universal latency/accuracy or open exchange availability. No more modelrequests, no storedchats or sourcecontent/vectorchanges.
- L16 - Recovery/closure: docs/ingestion-v2-verification.md captures proof, limits andremaining482unknownsources. Removed13ownedoutside-worktreescratchdirectories; durablebackups/privateartifacts retained. Existinguncommittedpromptfix/priorplanningdocs preserved outsideingestioncommits; MiUnisourceunchanged; nativeRDDstilldisabled; no push/PR/mainmutation. Engrammirrorremainsunavailable due missingregisteredhostidentity; actualtaskfile is recovery source.

- L17 - Final idempotencecheck publicCLI dry-run: matched6, affected0, no writes. Allsix tasklines readback withproof; documentation correctedhistorical initialemptycoverage versuscurrent14eligiblechunks. No extra regressiontestneededbecause allcriticalindependentprobes already represented. Fullcorpusclassification andbulknetworkcrawl not claimed; remaining482unknownsources remainexplicitfollow-up.
