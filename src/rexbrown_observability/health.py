"""Health endpoint registration for Starlette / FastAPI apps."""

from __future__ import annotations

import inspect
import logging
from typing import Any, Awaitable, Callable, Iterable

HealthCheck = Callable[[], Any | Awaitable[Any]]
log = logging.getLogger(__name__)


async def run_health_checks(checks: dict[str, HealthCheck] | None) -> dict[str, str]:
    results: dict[str, str] = {}
    for name, check in (checks or {}).items():
        try:
            outcome = check()
            if inspect.isawaitable(outcome):
                outcome = await outcome
            results[name] = "error" if outcome is False else "ok"
        except Exception:
            log.warning("health check failed", extra={"check": name}, exc_info=True)
            results[name] = "error"
    return results


def build_health_payload(service: str, version: str, checks: dict[str, str]) -> tuple[dict[str, Any], int]:
    degraded = any(v != "ok" for v in checks.values())
    body = {
        "status": "degraded" if degraded else "ok",
        "service": service,
        "version": version,
        "checks": checks,
    }
    return body, (503 if degraded else 200)


def _existing_paths(app: Any) -> set[str]:
    paths: set[str] = set()
    for route in getattr(app, "routes", []) or []:
        path = getattr(route, "path", None)
        if path is None:
            continue
        methods = getattr(route, "methods", None)
        if methods is None or "GET" in methods:
            paths.add(path)
    return paths


def register_health(
    app: Any,
    *,
    service: str,
    version: str,
    paths: Iterable[str],
    checks: dict[str, HealthCheck] | None = None,
) -> list[str]:
    """Register a GET health endpoint at each path not already routed. Returns the paths added."""
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    async def health(_: Request) -> JSONResponse:
        results = await run_health_checks(checks)
        body, status = build_health_payload(service, version, results)
        return JSONResponse(body, status_code=status)

    existing = _existing_paths(app)
    added: list[str] = []
    for path in paths:
        if not path or path in existing:
            continue
        app.add_route(path, health, methods=["GET"], name=f"health:{path}", include_in_schema=False)
        existing.add(path)
        added.append(path)
    return added
