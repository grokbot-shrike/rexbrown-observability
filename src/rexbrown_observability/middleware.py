"""Pure ASGI request-ID middleware with one INFO access line per request."""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable, Iterable

from .context import REQUEST_ID_HEADER, request_id_var, resolve_request_id

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_HEADER_BYTES = REQUEST_ID_HEADER.lower().encode("latin-1")
http_logger = logging.getLogger("http")


class RequestIDMiddleware:
    """Set ``request_id_var`` for the request, echo ``x-request-id``, log the request end.

    Pure ASGI (no ``BaseHTTPMiddleware``), so it works with streaming responses
    and does not break context propagation.
    """

    def __init__(
        self,
        app: ASGIApp,
        skip_paths: Iterable[str] = (),
        sentry_active: bool = False,
    ) -> None:
        self.app = app
        self.skip_paths = frozenset(skip_paths)
        self.sentry_active = sentry_active

    def _should_log(self, path: str) -> bool:
        return path not in self.skip_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming: str | None = None
        for name, value in scope.get("headers", ()):
            if name == _HEADER_BYTES:
                incoming = value.decode("latin-1", errors="replace")
                break
        rid = resolve_request_id(incoming)
        token = request_id_var.set(rid)
        if self.sentry_active:
            _set_sentry_tag(rid)

        status_holder = {"status": None}
        started = time.perf_counter()

        async def send_wrapper(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message.get("status")
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != _HEADER_BYTES
                ]
                headers.append((_HEADER_BYTES, rid.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        path = scope.get("path", "")
        method = scope.get("method", "")
        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException:
            if status_holder["status"] is None:
                status_holder["status"] = 500
            raise
        finally:
            if self._should_log(path):
                duration_ms = round((time.perf_counter() - started) * 1000, 3)
                http_logger.info(
                    "request",
                    extra={
                        "method": method,
                        "path": path,
                        "status": status_holder["status"],
                        "duration_ms": duration_ms,
                    },
                )
            request_id_var.reset(token)


def _set_sentry_tag(rid: str) -> None:
    try:
        import sentry_sdk

        sentry_sdk.set_tag("request_id", rid)
    except Exception:  # pragma: no cover - sentry must never break a request
        logging.getLogger(__name__).debug("could not set sentry request_id tag", exc_info=True)
