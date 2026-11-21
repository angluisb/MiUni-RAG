# Consult the existing personal schedule from chat

Status: implemented locally under the later user authorization in `odd/tasks/chat-context-schedule-rag.md`; real HTTP/browser latency and acceptance remain pending.
Repositories: MiUni API/Web and Python RAG. Baseline evidence: MiUni `91c24ad`; implementation: MiUni `4647b4a`, RAG `0706bad`.

## Requested outcome

> Hacer que puedo consultar el modulo donde se ve tu horario

Students should ask about the same saved schedule shown by MiUni's schedule
module. This is an improvement to an existing integration, not a new module.

## Existing capability and limitation

- `/horario` and the profile schedule section already exist:
  `MiUni.Web/src/routes/AppRoutes.jsx:19,30-36` and
  `components/HorarioSeccion.jsx:8,23-39`.
- `GET /api/Horario` reads the authenticated user's rows; individual lookups also
  check ownership: `MiUni.Api/Controllers/HorarioController.cs:12-37`.
- `BuildCampusQuestion` currently appends the entire academic profile, grades,
  weekly schedule, place catalog and campus timestamp to every ordinary question:
  `MiUni.Api/Controllers/ChatController.cs:231-271` and
  `Services/PerfilAcademico.cs:29-80`. Python retrieves using this combined text.
- An existing test explicitly expects that broad injection:
  `MiUni.Api.Tests/ChatControllerTests.cs:281-330`; intentionally update it when
  introducing data minimization, rather than silently breaking it.
- Schedule rows are student-entered or import-confirmed, not a live enrollment
  feed. PDF parsing does not itself persist the result:
  `HorarioController.cs:78-131`.
- Rows have ISO weekday 1-7 and local start/end times, but no term, holiday or
  cancellation fields: `Models/HorarioClase.cs:5-25`.

## Proposed behavior

1. Reuse a shared owner-filtered schedule query from the existing module. Resolve
   the user from authenticated server claims, never from browser/model arguments.
   Do not duplicate authorization in a weaker RAG-side SQL implementation.
2. Support "my schedule", today, tomorrow, a named weekday, current class and next
   class. Return all matching rows in deterministic order; preserve overlapping
   rows rather than choosing an arbitrary class.
3. Use an injectable campus clock and `America/Hermosillo`, reusing the existing
   helper (`PerfilAcademico.cs:84-93`). Current-class boundaries are `[start,end)`.
   Define next class across the next seven local calendar days, including Sunday
   rollover. Explicit historical/term questions remain unsupported unless the
   module later stores that information.
4. Distinguish no saved schedule from no classes on the requested day. Say when
   room/teacher is missing; never infer it. Explain that the answer describes the
   user's saved recurring schedule, not verified holiday/cancellation status.
5. Render routine schedule answers deterministically without HyDE, embeddings or
   Gemini. Link to the existing `/horario` route for review or edits.
6. For mixed schedule/institutional questions, supply only selected relevant
   schedule fields as typed untrusted context. Keep raw question, private context,
   place catalog and documentary query separate. Do not append all grades,
   credits and schedule to unrelated questions.
7. Classify "Rectoría opening hours" as an institutional-place question, not a
   personal timetable request. Ambiguous questions receive at most one necessary
   clarification. Personal-context retrieval never changes temporal document policy.
8. Read fresh schedule state for each request, or use explicitly user-scoped cache
   invalidation tied to schedule edits/deletion. No cross-user schedule cache.
   Resolve free-text rooms through the existing canonical map resolver only when
   unambiguous; never invent place IDs or directions.

## Acceptance examples

| Question/state | Required observable result |
| --- | --- |
| "What class do I have now?" | Uses the fixed campus clock and exact saved `[start,end)` interval. |
| "What do I have tomorrow?" on Sunday night | Correct Monday rows in campus local time. |
| "What is my next class?" after Friday's last class | Next saved block within the defined seven-day horizon; no invented session. |
| No rows saved | Explain no schedule is saved and link to `/horario`. |
| Rows exist, requested day empty | Explain no classes are saved for that day, not that the entire schedule is absent. |
| Missing room/teacher or overlapping rows | Preserve missingness and all matching rows. |
| Two users have identically named subjects | Each sees only their own rows. Forged IDs do not alter ownership. |
| Edit the schedule, then ask again | The next answer reflects the edit. |
| Ask about a scholarship | No entire schedule, grade history or unnecessary profile is sent to the model. |
| Ask about a holiday or past semester | State the weekly model's limitation; do not imply an authoritative live calendar. |

## Delivery and verification plan

- H1: shared owner-filtered read service and fixed-clock schedule selection tests.
- H2: deterministic personal-schedule route and canonical `/horario` link.
- H3: typed minimal mixed-query context, replacing broad profile augmentation.
- H4: privacy, edit freshness, empty-state and JSON/streaming parity verification.
- Observe RED before implementation. Run existing `.NET` chat/schedule/profile/
  stream tests, frontend `horarioUtils`/stream tests, and Python contract tests.
- Suggested performance target, not yet measured: warm local schedule-only
  requests below 300 ms p95 with zero model calls. Establish enough samples before
  accepting this target. Measure mixed questions separately from deterministic ones.

## Boundaries and risks

No chat-driven schedule edits/imports/deletes, live university enrollment sync,
grade analysis, holiday database or new schedule schema is included.

Security/privacy, campus time boundaries and the shared internal request contract
need independent verification. Coordinate the typed context with
`chat-conversation-memory.md`; do not create conflicting request formats.

This specification does not authorize implementation, migrations, user-data
exports, publication or provider requests.
