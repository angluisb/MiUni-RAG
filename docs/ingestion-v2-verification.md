# Ingestion v2: verified implementation and first metadata rollout

Date: 2026-11-17. Branch: `feat/ingestion-v2`. The existing ingestion spec was
executed; no separate feature specification or new MiUni migration was needed.

## Outcome

The crawlers now check robots policy before resource requests and redirects.
Reviewed temporal metadata reaches the canonical document columns, and a separate
backup-backed tool updates existing classifications without reindexing.

The first reviewed six-source batch was applied to the existing local PostgreSQL
RAG database on host port 5433. Current retrieval now has **14 eligible chunks**,
instead of zero. This is an initial coverage restoration, not classification of
the entire university corpus.

| State | Before | After |
| --- | ---: | ---: |
| Current documents | 0 | 2 |
| Historical documents | 0 | 3 |
| Replaced documents | 0 | 1 |
| Unknown documents | 488 | 482 |
| Stored documents | 488 | 488 |
| Stored chunks / embeddings | 1379 / 1379 | 1379 / 1379 |
| Eligible current chunks | 0 | 14 |

The live temporal filter remains enabled. No unknown-source fallback was enabled.

## Reviewed sources and evidence

The exact URLs, source IDs, verification timestamps and rationale are versioned
in `data/sources/document_temporal_metadata.json`.

- **Current:** the 2020 practices regulation is linked by the current
  [official DAE practices portal](https://dae.unison.mx/practicasprofesionales.html).
  Live PDF bytes match both stored download metadata and the stored raw PDF hash.
  Its transitional provisions and program-specific qualifications remain in the
  source; no unknown effective date was manufactured.
- **Current:** the [official Buddy program page](https://movilidad.unison.mx/buddy-program/)
  is linked by current SCMI navigation. Its substantive text matches the indexed
  and raw content after the explicitly recorded whitespace normalization; this
  does not establish an open outgoing-exchange call.
- **Replaced:** the 2017 practices link page identifies that older edition, which
  the 2020 regulation expressly abrogates. No speculative replacement UUID was set.
- **Historical:** ASU 2026-1, Spain 2027-1 and CONAHEC 2027-1 application calls have
  evidenced past deadlines; the official portal explicitly marks the latter two
  closed. Future mobility periods do not imply open applications. Historical call
  status does not assert expiry of obligations for already accepted students.

The three historical PDF hashes were also matched against actual stored raw
files. Publication years and effective dates remain absent when not proven.

## Verification

- Parent integrated Python suite: **110 passed**, PostgreSQL TEMP tests enabled,
  no skips. Focused tests observed meaningful RED before implementation.
- Independent feature verifier: **77 assertions passed**, covering S1-S6 with
  fake HTTP and isolated PostgreSQL TEMP state; existing CLI output matched
  baseline `348117b` where behavior was not intentionally changed.
- Fresh local integration: RAG `/health/ready` HTTP 200, model/database ready;
  MiUni API launched through `scripts/dev.ps1 -Action api`, `/api/Lugar` HTTP 200
  with 51 places. No user seeding or migration was invoked.
- A second limited independent live check confirmed all six canonical rows match
  the manifest, before-values backup contents, unknown exclusion and eligibility:
  current 14 chunks/2 documents; historical 27/6; period `2027-1` 9/2.
- `pip check` passed. Missing ingestion packages were installed at their existing
  `requirements.txt` pins; dependency files were not changed.
- No stored chunk, embedding, source ID or non-temporal document field changed.
  Independently recomputed before/after fingerprints match:
  - Documents: `5b0cb7ec3a6609c202016d7ccd774c28` (temporal columns excluded).
  - Full chunk rows: `daee1f1707f7ede404f9a8e2ea1b51e8`.

Robots tests cover allow/disallow, agent selection, wildcards/longest matching,
normalization, every redirect hop, cache bounds/expiry, policy refresh and delays.
The documented implementation is a supported subset, not a claim of complete
RFC 9309 conformance. Only explicit robots 404/410 absence permits access;
authorization/rate errors, server/network errors and invalid policy responses
remain blocked. No bulk institutional crawl was run during this rollout.

## Real answer smoke checks

Two direct Python streaming requests used Gemini after classification:

| Question | Retrieved chunks | First text | Complete |
| --- | ---: | ---: | ---: |
| `Que documentos ocupo para mis practicas?` | 8 | 5.161 s | 6.306 s |
| `Que opciones ofrece el programa Buddy de movilidad?` | 8 | 5.567 s | 6.325 s |

Both returned HTTP 200 and substantive answers with official-source links.
The practice answer's medical-service certificate and activity-report claims
were located in the exact selected source chunks. Buddy facts used its reviewed
program page; unrelated practice candidates also appeared in the second context.
This is evidence of restored useful source access, not a universal relevance or
semantic-accuracy score. Open exchange availability was not proven or promised.

Do not compare these longer grounded answers directly with earlier shorter
no-information responses as a latency improvement. Two samples cannot establish
p95 or an integrated browser/.NET latency target. No private academic profile,
authenticated chat persistence or conversation-memory feature was exercised.

## Safety, recovery and remaining work

- A full private custom-format dump preceded the rollout; a second exclusive,
  fsynced before-values backup outside Git was required before committing the six
  metadata updates. Backups and raw answer artifacts are not repository files.
- Ignored evidence: `.cache/ingestion-v2/` contains baseline, apply and answer/
  source proofs; `.cache/backups/` contains the private full backup.
- Metadata-only backfill is idempotent and separate from indexing, which can prune
  stale chunks. Missing metadata preserves existing classification on reimport.
- **482 documents remain unknown.** Review additional sources from authoritative
  evidence; never infer current validity from a title, URL year or successful fetch.
- Broader factual coverage, integrated-profile query separation, history and
  schedule improvements remain separate work. No whole-corpus reingestion was run.
- Changes are local work-unit commits; no push, PR, main change or native review
  approval is implied. The user's disabled review preference was preserved.
