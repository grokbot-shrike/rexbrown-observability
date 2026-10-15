"""Request-ID context and helpers for propagating it to outgoing calls."""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from typing import Any, MutableMapping

REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Return the current request id, or None outside a request context."""
    return request_id_var.get()


def is_valid_request_id(value: str | None) -> bool:
    return bool(value) and _VALID_REQUEST_ID.match(value) is not None  # type: ignore[arg-type]


def new_request_id() -> str:
    return uuid.uuid4().hex


def resolve_request_id(incoming: str | None) -> str:
    """Accept a well-formed incoming id, otherwise generate a fresh one."""
    if incoming is not None and is_valid_request_id(incoming):
        return incoming
    return new_request_id()


def inject_request_id(headers: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Add X-Request-ID to a mutable headers mapping in place (if one is set).

    Works with plain dicts, ``requests`` session headers and ``httpx.Headers``.
    Does not overwrite an existing X-Request-ID.
    """
    rid = get_request_id()
    if rid is None:
        return headers
    for key in headers.keys():
        if isinstance(key, str) and key.lower() == REQUEST_ID_HEADER.lower():
            return headers
    headers[REQUEST_ID_HEADER] = rid
    return headers


def outgoing_headers(headers: MutableMapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a new dict of headers with X-Request-ID added."""
    out: dict[str, Any] = dict(headers) if headers else {}
    inject_request_id(out)
    return out


def httpx_event_hook(request: Any) -> None:
    """httpx request event hook: ``httpx.Client(event_hooks={"request": [httpx_event_hook]})``."""
    inject_request_id(request.headers)
