# rexbrown-observability

Shared observability for Rex Brown Python services. One call gives you:

- **JSON logging** to stdout, one line per event, following `docs/logging-standard.md`
  in `rexbrown-plan` (Loki-friendly, no files, no colour).
- **Request IDs**: pure-ASGI middleware that accepts/generates `X-Request-ID`, puts it
  in a contextvar so every log line in that request carries it, echoes it back, and
  logs one `request` line per request (health probes excluded).
- **Health endpoint** `GET /health` returning `ok`/`degraded` with per-check results and
  HTTP 503 when degraded.
- **Sentry / GlitchTip** initialised only when `SENTRY_DSN` (or `GLITCHTIP_DSN`) is set.
- **Redaction** of secrets and PII in log fields and messages.

Runtime dependency: stdlib only. Extras pull in Starlette and sentry-sdk.

This README is written for AI coding agents converting an existing repo. Follow it
literally.

## Install

Add to `pyproject.toml` / `requirements.txt`:

```
rexbrown-observability @ git+https://github.com/grokbot-shrike/rexbrown-observability@v0.1.1
```

With extras (FastAPI apps want both):

```
rexbrown-observability[fastapi,sentry] @ git+https://github.com/grokbot-shrike/rexbrown-observability@v0.1.1
```

| Extra     | Adds            | When                                        |
|-----------|-----------------|---------------------------------------------|
| `fastapi` | `starlette`     | Any FastAPI / Starlette app (middleware, /health). FastAPI already depends on Starlette, so this is only needed for bare ASGI apps. |
| `sentry`  | `sentry-sdk>=2` | Any service that should report to GlitchTip. |
| `dev`     | pytest, httpx, fastapi, sentry-sdk | Developing this package. |

### Dockerfile note

`python:*-slim` images do not ship `git`, so a `git+https://` requirement fails at
`pip install`. Either install git first:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends git \
 && pip install --no-cache-dir -r requirements.txt \
 && apt-get purge -y git && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
```

or, simpler, use the tarball URL which needs no git:

```
rexbrown-observability[fastapi,sentry] @ https://github.com/grokbot-shrike/rexbrown-observability/archive/refs/tags/v0.1.1.tar.gz
```

## Integration: three lines

```python
from fastapi import FastAPI
from rexbrown_observability import setup

app = FastAPI()
setup(app, service="pickflow", version="1.4.2", health_checks={"db": ping_db})
```

Call `setup()` once, at import time of your `main.py`, **before** any other logging
happens and before uvicorn starts. `service` must be the fixed name for the repo from
the logging standard (`pickflow`, `vigil-api`, `clockinout-api`, `replen-mw`,
`goods-in-mw`, `stock-take-mw`, `returns-api`, `rugby-goods-out`, `connect-server`,
`connect-huey`, `warehouse-events`).

Workers without HTTP (huey, TCP servers) call `setup(service="connect-huey")` with no
app in their package `__init__.py`.

### `setup()` parameters

```python
setup(
    app=None,                    # FastAPI/Starlette app; omit for workers
    service="pickflow",          # required, keyword-only
    version=None,                # default: APP_VERSION env, else "unknown"
    env=None,                    # default: ENV env, else "dev"
    health_path="/health",       # primary health route
    health_checks=None,          # {"db": callable} sync or async; raise/False => "error"
    extra_health_paths=(),       # legacy paths to keep: ("/orders/health", "/healthz")
)
```

Idempotent: calling it twice does not duplicate handlers, middleware or routes. It never
overwrites a route you already registered at a health path.

### Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `ENV` | `dev` | `prod` / `staging` / `dev`; becomes the `env` field and Sentry environment |
| `LOG_LEVEL` (fallback `LOGS_LEVEL`) | `INFO` | Root log level |
| `LOG_FORMAT` | `json` | `text` for a plain one-line format in local dev |
| `APP_VERSION` | `unknown` | Used when `version=` is not passed; Sentry release |
| `SENTRY_DSN` / `GLITCHTIP_DSN` | empty | Empty means the SDK is never imported |

## Log line fields

Every line is a JSON object:

| Field | Always | Notes |
|---|---|---|
| `ts` | yes | UTC ISO-8601 with microseconds: `2026-10-15T08:50:01.123456Z` |
| `level` | yes | `DEBUG` `INFO` `WARNING` `ERROR` `CRITICAL` |
| `service` | yes | From `setup(service=...)` |
| `env` | yes | From `ENV` |
| `logger` | yes | Python logger name (`__name__`) |
| `msg` | yes | Short static phrase. Email addresses in it are masked. |
| `request_id` | in a request | From `X-Request-ID` or generated `uuid4().hex` |
| `file`, `line` | yes | Source location of the log call |
| `exc_info` | on error | Full traceback text when `logger.exception()` / `exc_info=True` |
| *anything in `extra=`* | when given | `order_id`, `employee_id`, `channel_id`, `duration_ms`, … merged at top level |

The `http` logger emits one `request` line per request with `method`, `path`, `status`,
`duration_ms`. Health paths are skipped.

Any `extra` key whose name contains (case-insensitive) `password`, `passwd`, `secret`,
`token`, `authorization`, `api_key`, `apikey`, `cookie`, `dsn`, `email` or `pin` is
replaced with `"[REDACTED]"`, recursively inside dict values.

Reserved keys (`ts`, `level`, `service`, `env`, `logger`, `msg`, `file`, `line`,
`exc_info`) passed via `extra` are emitted as `extra_<key>` so they cannot clobber the
envelope.

## Request ID helpers

```python
from rexbrown_observability import get_request_id, outgoing_headers, inject_request_id, httpx_event_hook, async_httpx_event_hook

get_request_id()                         # current id or None
requests.get(url, headers=outgoing_headers({"Accept": "application/json"}))
inject_request_id(session.headers)       # mutate an existing headers mapping in place
httpx.Client(event_hooks={"request": [httpx_event_hook]})   # automatic for httpx
httpx.AsyncClient(event_hooks={"request": [async_httpx_event_hook]})  # AsyncClient awaits hooks: use the async one
```

Uvicorn, `uvicorn.error`, `uvicorn.access`, `huey` and `fastapi` loggers have their own
handlers removed and propagate to root, so their output is JSON too. Run uvicorn with
`--no-access-log` if you do not want both uvicorn's access line and ours.

## Checklist for converting a repo

Work through every item; do not skip the verification step.

1. **Add the dependency** (see Install) and the three-line `setup()` call at the top of
   `main.py` (or `app/__init__.py` for workers). Delete the repo's own
   `logging_config.py` / `logging_setup.py` / `dictConfig` blocks and any
   `logging.basicConfig` calls.
2. **Remove `print()`** from application code. Replace with
   `logger = logging.getLogger(__name__)` and `logger.info(...)`. Scripts invoked as
   CLI tools may keep print for their own stdout output only.
3. **Tracebacks on errors.** Inside `except` blocks use
   `logger.exception("short phrase", extra={...})`, never `logger.error(str(e))` and
   never `logger.error(f"... {e}")`. ERROR level without `exc_info` is a bug.
4. **No silent swallowing.** `except Exception: pass` becomes either
   `logger.exception(...)` and re-raise, or `logger.warning("why it is safe to ignore")`.
5. **Levels.** `DEBUG` diagnostics; `INFO` one line per request end / job cycle / state
   change; `WARNING` recoverable and expected (retry, upstream 4xx, validation reject);
   `ERROR` operation failed and needs a human, always with traceback; `CRITICAL` service
   cannot do its job.
6. **Static messages, ids in `extra`.** Write
   `logger.info("order picked", extra={"order_id": order_id})`, not
   `logger.info(f"order {order_id} picked")`. Use the service's natural key:
   `order_id`, `audit_id`, `grn_id`, `return_id`, `stock_take_id`, `job_id`, `user_id`,
   `employee_id`, `channel_id`. Keep keys snake_case and stable.
7. **No PII or secrets**, even in DEBUG: no passwords, API keys, bearer/JWT tokens,
   cookies, DSNs, connection strings, employee names, badge numbers, PINs, emails,
   phone numbers, customer addresses, Auth0 claims, request/response bodies, SQL with
   values, raw machine payloads. Redaction is a safety net, not a licence.
8. **Health.** Pass `health_checks={"db": ping}` where `ping` does a real DB round-trip.
   Keep legacy paths via `extra_health_paths=`. Add a Dockerfile `HEALTHCHECK` that
   curls the health path.
9. **Compose env.** Add `ENV`, `LOG_LEVEL`, `APP_VERSION`, `SENTRY_DSN=` (empty by
   default) to the compose file and keep
   `logging: {driver: json-file, options: {max-size: 10m, max-file: "3"}}`.
10. **Outbound calls.** Pass `outgoing_headers()` or the httpx hook so the request id
    follows calls between services.
11. **Verify.** Run the service, hit an endpoint and `/health`, and confirm:
    `docker logs` shows only JSON lines; every line has `service`, `env`, `request_id`
    on request-scoped lines; a forced exception produces one ERROR line with
    `exc_info`; `/health` returns 503 when the DB check fails; response bodies and
    status codes are unchanged; the existing test suite passes.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e '.[dev,fastapi,sentry]'
pytest
```
