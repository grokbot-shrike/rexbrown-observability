"""rexbrown_observability: JSON logging, request IDs, health endpoint, optional Sentry.

Typical use::

    from fastapi import FastAPI
    from rexbrown_observability import setup

    app = FastAPI()
    setup(app, service="pickflow", version="1.4.2", health_checks={"db": ping_db})
"""

from __future__ import annotations

import logging
import os
from typing import Any, Iterable

from .context import (
    REQUEST_ID_HEADER,
    get_request_id,
    httpx_event_hook,
    async_httpx_event_hook,
    inject_request_id,
    outgoing_headers,
    request_id_var,
)
from .health import HealthCheck, register_health
from .logging_setup import JsonFormatter, TextFormatter, configure_logging
from .middleware import RequestIDMiddleware
from .redaction import REDACTED, mask_emails, redact_fields
from .sentry import init_sentry
from .sentry import is_active as sentry_is_active

__version__ = "0.1.2"

__all__ = [
    "setup",
    "get_request_id",
    "request_id_var",
    "RequestIDMiddleware",
    "outgoing_headers",
    "inject_request_id",
    "httpx_event_hook",
    "async_httpx_event_hook",
    "JsonFormatter",
    "TextFormatter",
    "redact_fields",
    "mask_emails",
    "REDACTED",
    "REQUEST_ID_HEADER",
    "HealthCheck",
    "sentry_is_active",
    "__version__",
]

_MIDDLEWARE_FLAG = "_rexbrown_observability_middleware"
_log = logging.getLogger(__name__)


def setup(
    app: Any | None = None,
    *,
    service: str,
    version: str | None = None,
    env: str | None = None,
    health_path: str = "/health",
    health_checks: dict[str, HealthCheck] | None = None,
    extra_health_paths: Iterable[str] = (),
) -> None:
    """Configure logging, Sentry, request-ID middleware and health routes in one call.

    Safe to call more than once; handlers and middleware are not duplicated.
    """
    env = env or os.getenv("ENV") or "dev"
    version = version or os.getenv("APP_VERSION") or "unknown"

    configure_logging(service=service, env=env)
    sentry_on = init_sentry(service=service, env=env, version=version)

    if app is None:
        return

    health_paths = [health_path, *extra_health_paths]
    health_paths = [p for p in health_paths if p]

    state = getattr(app, "state", None)
    if state is None or not getattr(state, _MIDDLEWARE_FLAG, False):
        app.add_middleware(
            RequestIDMiddleware,
            skip_paths=health_paths,
            sentry_active=sentry_on,
        )
        if state is not None:
            setattr(state, _MIDDLEWARE_FLAG, True)

    register_health(
        app,
        service=service,
        version=version,
        paths=health_paths,
        checks=health_checks,
    )
