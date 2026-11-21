# Conversation memory within a MiUni chat

Status: implemented locally under the later user authorization in `odd/tasks/chat-context-schedule-rag.md`; final real-provider follow-up and HTTP/browser acceptance remain pending.
Repositories: MiUni API/Web and Python RAG. Baseline evidence: MiUni `91c24ad`; implementation: MiUni `4647b4a`, RAG `0706bad`.

## Requested outcome

> Hacer que el chat recuerde anteriores mnesajes del chat

A follow-up should use previous completed turns in the selected conversation,
including after a page reload. This is conversation context, not permanent
cross-chat or cross-user memory.

## Current behavior and evidence

- MiUni stores and displays history, but only sends the current augmented question
  to RAG: `MiUni.Api/Controllers/ChatController.cs:28-57,88-89`.
- Session ownership is already checked against the authenticated user; history
  reads/deletes use both user and session: `ChatController.cs:162-228`.
- The internal client sends only `Question`: `MiUni.Api/Services/RagClient.cs:50-71`;
  Python accepts only `question`: `app/schemas/chat.py:4-5`.
- Python constructs a new prompt on every request:
  `app/services/llm_service.py`, `_build_messages`.
- The frontend already selects sessions and reloads saved history:
  `MiUni.Web/src/pages/Chat.jsx:21-34,73-118`.
- Partial/cancelled assistant streams are not persisted; retain that invariant:
  `MiUni.Api.Tests/ChatStreamingTests.cs:51-71`.

## Proposed behavior

1. Load context on the server using authenticated user + owned session. Never
   accept a browser/model-supplied user ID as authority. An absent session starts
   a new conversation without borrowing another session's history.
2. Add optional typed history to the internal RAG contract, separate from the raw
   current question. Old question-only callers retain their current behavior.
   Accept only bounded `user`/`assistant` history entries, never `system` or `tool`.
3. Select a bounded, deterministic snapshot of completed turns before the current
   turn. Exclude the just-persisted current user row by identity, not text equality.
   Do not send partial assistant output or orphan user rows from failed turns as
   if they were a completed exchange.
4. Proposed initial budgets: at most 12 history messages and 4,000 history tokens,
   configurable and separate from the current question and documentary budget.
   Drop oldest whole turns first; do not silently create persistent summaries.
   Define a deterministic token-counting method before implementation.
5. Preserve message roles. History and retrieved documents remain untrusted data;
   saved instructions cannot override the system, expand permissions or become
   evidence of current institutional requirements.
6. Resolve follow-up references for retrieval using only the bounded context.
   Preserve the original user text for storage/display. A rewritten search query
   cannot change ownership, temporal policy or tool authorization.
7. Key rewritten-query/HyDE caches by the effective contextual query and policy
   version. A short input such as "and the documents?" must not reuse a different
   conversation's antecedent. Do not cache private answers globally.
8. Preserve JSON/streaming equivalence, cancellation and complete-only assistant
   persistence. Proposed concurrency policy: one active turn per owned session;
   an overlapping turn receives a clear conflict response, while other sessions
   remain independent. Define stable ordering beyond timestamp ties.

## Acceptance examples

| Scenario | Required observable result |
| --- | --- |
| "I want information about academic exchanges" then "what documents do I need?" | Follow-up refers to exchanges, not unrelated practices; unsupported requirements remain unconfirmed. |
| Reload the selected chat, then ask a follow-up | Same bounded server history is available. |
| Start a new conversation or select another owned conversation | Only the newly selected conversation contributes context. |
| Supply another user's session ID | Denied; no foreign history reaches the provider or logs. |
| Repeat exactly the same user message twice | Each current turn appears once; text equality does not delete legitimate history. |
| Delete a conversation, then attempt to resume it | Deleted context cannot be recovered from a private-context cache. |
| A saved message says "ignore the system" | It stays a user/assistant message and grants no new authority. |
| Interrupt a stream or provider failure | No partial assistant becomes subsequent completed-turn context. |
| Exceed either history budget | Deterministic oldest-turn truncation; current question remains intact. |

## Delivery and verification plan

- M1: owned-history selection and snapshot/limit tests in MiUni.
- M2: additive C#/Python contract, role validation and prompt composition tests.
- M3: follow-up retrieval and contextual cache regression tests.
- M4: JSON/streaming, reload/delete and concurrency acceptance checks.
- Observe RED before each behavior change. Run `.NET` chat/history/stream suites,
  Python contract/message tests, and existing frontend stream tests.
- Before/after measurements: first text, completion, history tokens, retrieval
  sources and antecedent correctness on paired single-turn/follow-up examples.
  Do not claim success from HTTP 200 or prompt text alone.

## Boundaries and risks

No cross-chat memory, indefinite retention, schedule mutation, automatic source
classification or new database is included. Reuse existing history retention and
deletion policy. Do not log raw private histories for latency telemetry.

Security/privacy, shared internal contracts and simultaneous turns require
independent verification. This proposal does not authorize code, migrations,
provider calls, publication or changes to the user's review preference.
