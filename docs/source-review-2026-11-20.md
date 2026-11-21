# Source review: 482 previously unknown documents

Status: 263 reviewed metadata updates applied on 2026-11-21; 219 sources remain unknown.
Source captures: campus 2026-11-20 evening / UTC 2026-11-21 early.

## Goal and ordered roadmap

1. Validate and apply supported metadata without changing document content or vectors.
2. Restore useful integrated RAG answers, separate raw questions from excessive academic context, and measure quality plus latency.
3. Add bounded, owned per-conversation memory, following `specs/chat-conversation-memory.md`.
4. Reuse the existing owned schedule module for minimal read-only context and deterministic answers, following `specs/chat-personal-schedule.md`.

The current execution unit is step 1. Later features remain separate deliverables.
Use local scripts for mechanical checks and inexpensive models for narrow reading;
never repeat the whole-source investigation merely to resume this work.

## Completed batch results

| New classification | Sources |
| --- | ---: |
| Current | 223 |
| Historical | 33 |
| Replaced | 7 |
| Remain unknown | 219 |
| Reviewed total | 482 |

The existing six classifications are retained byte-for-byte in the combined manifest.
There are 269 total manifest entries, and exactly 263 database rows were updated.

The live corpus now has 225 current, 36 historical, 8 replaced and 219 unknown
documents. Current retrieval has **952 eligible chunks**, up from 14. All 488
documents and 1,379 stored chunk/vector rows retain their original non-temporal
content fingerprints. The previous six classifications are unchanged.

## Why 219 sources remain unknown

| Evidence gap | Sources |
| --- | ---: |
| Stored/live content mismatch | 150 |
| Applicability, dates or conflicting guidance | 32 |
| Insufficient substantive content | 25 |
| Access or robots-policy obstacle | 7 |
| Current publisher authority not established | 5 |

Per-source IDs, URLs and reasons are recorded in
`data/sources/document_temporal_review_pending.json`. Live/raw snapshots and full
audit records remain private under `.cache/source-review-20261120/`.

A mismatch needs safe, version-preserving reingestion, not relabelling the old
snapshot current. Contradictory requirements need authoritative reconciliation.
Publication dates, plan codes, copyright years and HTTP 200 are not validity rules.
A current curriculum reference does not mean admissions are open or that every
cohort follows that plan. No semester or effective dates were guessed from plan codes.

## Validation so far

- Mechanical checks cover every 482 distinct IDs and exact source URLs; no pending
  records, duplicates or accidental changes to the original six entries.
- Strict manifest parsing passed for 269 entries.
- Public CLI dry-run matched 269 sources and proposed 263 changes. After apply, the
  same dry-run matched 269 sources and proposed **zero** changes. All 269 canonical
  records match the reviewed manifest exactly.
- A Windows legacy-console bug was reproduced: an accented URL could fail JSON
  printing after processing. JSON escaping now preserves the same decoded URL;
  its subprocess regression passed after observed RED. No transaction logic changed.
- One inexpensive independent reader checked coverage and reconciled seven PDF
  cases using captured/stored bytes, every indexed PDF hash and ten publisher
  links. Text ordering differed across extractors; the file versions did not.
  This is scoped provenance validation, not a second full semantic reading of
  every page. No row was applied merely because its URL responds.
- The Unicode regression and full local suite passed: **111 tests**, with
  PostgreSQL TEMP tests enabled. No provider API calls were used in this batch.

## Retrieval checks and next work

Read-only lexical checks now return up to eight chunks each for scholarship,
practice, mobility and engineering terms. These are retrieval checks, not an
answer-quality score or an end-to-end latency benchmark.

A concrete next RAG issue was reproduced: `titulacion` returns zero lexical hits,
while `titulación` returns eight; both practice spellings return eight. The
Abogacía term still returns zero with either spelling. Input normalization and
remaining source coverage must be investigated separately; no retrieval logic
was changed during this classification batch.

The 150 content-version mismatches need **version-preserving** reingestion, not
blind overwriting of historical snapshots. The other 69 unknown cases need better
authority, substantive content, access or clarification. This remains a distinct
follow-up from applying already-supported classifications.

## Safety and boundaries

A fresh full private backup preceded application. An additional exclusive, fsynced
before-values backup outside Git was created before the transaction committed,
with the expected database name and reviewed source IDs.
Unknown sources stay excluded under the enabled temporal filter. No source body,
embedding, shared schema, user profile, chat or schedule is changed by this batch.
No provider API or bulk source fetch will be repeated for this final validation.
