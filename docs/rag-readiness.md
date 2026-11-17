# Check RAG readiness before routing traffic

Use `GET /health/ready` for traffic admission and `GET /health/live` for process
liveness. Startup finishes the required embedding warmup and PostgreSQL check
before serving normal traffic when `RAG_ENABLED=true` and
`RAG_WARMUP_ON_STARTUP=true`.

## Health states

Readiness returns HTTP 200 only when both required dependencies are ready, or RAG
is disabled. Otherwise it returns HTTP 503. Its JSON contains `status`, `model`
and `postgresql` fields; raw exceptions and connection details are never included.

| Configuration or outcome | Model | PostgreSQL | Readiness |
| --- | --- | --- | --- |
| Warmup and database check succeed | `ready` | `ready` | 200 |
| Warmup fails | `failed` | Checked independently | 503 |
| Database check fails | Warmup result | `failed` | 503 |
| Explicit warmup optout | `not_warmed` | `not_checked` | 503 |
| RAG disabled | `disabled` | `disabled` | 200 |

Each readiness request repeats the read-only repository validation, so database
disconnects and recovery are reflected in the response. Connection and statement
timeouts use the existing repository configuration. No migration is applied.

## Failure and compatibility

A failed required warmup leaves the process alive, but both JSON and streaming
chat return HTTP 503 before starting retrieval or generation. Restart the service
after correcting a model startup failure. Database recovery is detected by the
next readiness probe without reloading the model.

`RAG_WARMUP_ON_STARTUP=false` remains an explicit compatibility optout: chat keeps
its previous lazy behavior, no startup database/model access is forced, and
readiness honestly reports that the model has not been warmed. Do not use this
optout when guaranteeing the first user avoids cold model loading.

## Local verification

Run `venv/Scripts/python.exe -m unittest discover -s tests -p test_readiness.py -v`.
Tests inject fake model and database dependencies; they need no external service.
