# Bounded conversation context

Both `POST /chat` and `POST /chat/stream` accept the same additive request.
Question-only clients keep their existing call and response shape.

```json
{
  "question": "que documentos necesito?",
  "history": [
    {"role": "user", "content": "Quiero un intercambio academico"},
    {"role": "assistant", "content": "Puedo ayudarte con intercambios."}
  ],
  "personal_context": {
    "campus_now": "2026-11-21T09:00:00-07:00",
    "schedule": [
      {"subject": "Math", "day": 1, "start": "09:00", "end": "10:00", "room": null, "teacher": null}
    ]
  }
}
```

## Limits and trust

- History defaults to empty and must contain completed alternating user/assistant
  pairs. System/tool roles, blank content and incomplete turns are rejected.
- Python independently drops oldest complete turns until at most 12 messages and
  4,000 UTF-8 content bytes remain. Bytes conservatively bound byte-tokenizer
  tokens; this is not a model-token estimate. No summary is persisted.
- Wire validation rejects more than 128 messages, more than 64,000 total history
  content bytes, or an individual content value above 4,000 UTF-8 bytes. The raw
  question is limited to 8,000 characters and is never included in history budget.
- Personal context allows only a recurring schedule (at most 100 entries) and
  campus clock. `day` is an ISO weekday integer, Monday=1 through Sunday=7.
  Subject/day/start/end are required; room/teacher are nullable. Unknown personal
  fields are rejected; no grades or full profile belong in this payload.
- The authenticated MiUni server owns session selection, history ownership,
  completed-turn selection and fresh schedule acquisition. Python does not use
  browser-provided IDs to authorize access and does not persist private context.

## Retrieval and generation

Elliptical follow-ups use the nearest bounded user antecedent for search. Assistant
content never becomes a retrieval query. A standalone question stays unchanged;
the raw question remains the final human message, once, and roles are preserved.
History and personal context are explicitly untrusted and not institutional proof.

Contextual requests disable shared HyDE and embedding cache reads/writes. Lexical,
dense and reranking inputs use the effective query. Only the raw current question
can broaden temporal scope: an explicit `YYYY-N` period selects that period and
explicit historical/past wording selects history; otherwise current-only applies.
HyDE cannot broaden this scope from antecedent text. Legacy question-only temporal
classification is unchanged. No private answers or rewritten histories are cached.

Successful HyDE enriches dense retrieval instead of replacing the original query:
both the original effective query and hypothetical passage search under the same
temporal policy, then reciprocal-rank fusion combines them with lexical results.
Each embedding retains its own normalized query/model/pipeline cache key. If HyDE
fails or is disabled, only the original dense search runs. Identical original and
hypothetical text is searched once. Embedding/vector timing metrics sum branch work
(which may overlap), while total retrieval latency measures wall-clock time. An
aggregate embedding-cache hit means every dense branch hit; any miss reports miss.

## Verification

`venv/Scripts/python.exe -m unittest discover -s tests -p test_conversation_context.py -v`
checks limits, roles, untrusted personal fields, follow-up search, temporal scope,
cache bypass and JSON/stream context forwarding without provider calls.

## Configurable budgets

Python CHAT_HISTORY_MAX_MESSAGES (2-12, default12) and CHAT_HISTORY_MAX_BYTES (128-4000, default4000) can lower history budgets. MiUni uses Chat__HistoryMaxMessages and Chat__HistoryMaxBytes within the same hard bounds. Both boundaries discard oldest whole turns. Raw question-only callers keep their existing length behavior.
