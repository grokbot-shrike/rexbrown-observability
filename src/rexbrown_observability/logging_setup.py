"""Root logging configuration: one JSON line per event on stdout."""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import sys
from typing import Any

from .context import get_request_id
from .redaction import REDACTED, is_sensitive_key, mask_emails, redact_value

HANDLER_NAME = "rexbrown_observability"
NOISY_LOGGERS: tuple[str, ...] = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "huey",
    "fastapi",
)

# Attributes every LogRecord has; anything else was supplied via ``extra=``.
_STANDARD_ATTRS: frozenset[str] = frozenset(
    {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "message", "asctime",
        "color_message",  # uvicorn adds an ANSI-coloured copy of msg
    }
)

_RESERVED_OUTPUT_KEYS: frozenset[str] = frozenset(
    {"ts", "level", "service", "env", "logger", "msg", "request_id", "file", "line", "exc_info"}
)


def _format_ts(created: float) -> str:
    dt = _dt.datetime.fromtimestamp(created, tz=_dt.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def record_extras(record: logging.LogRecord) -> dict[str, Any]:
    """All non-standard attributes that were attached to the record via ``extra``."""
    return {
        k: v
        for k, v in record.__dict__.items()
        if k not in _STANDARD_ATTRS and not k.startswith("_")
    }


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str, env: str) -> None:
        super().__init__()
        self.service = service
        self.env = env

    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        message = mask_emails(record.getMessage())
        data: dict[str, Any] = {
            "ts": _format_ts(record.created),
            "level": record.levelname,
            "service": self.service,
            "env": self.env,
            "logger": record.name,
            "msg": message,
        }
        rid = get_request_id()
        if rid is None:
            rid = getattr(record, "request_id", None)
        if rid is not None:
            data["request_id"] = rid
        data["file"] = record.pathname
        data["line"] = record.lineno
        if record.exc_info:
            data["exc_info"] = self.formatException(record.exc_info)
        elif record.exc_text:
            data["exc_info"] = record.exc_text
        if record.stack_info:
            data["stack_info"] = self.formatStack(record.stack_info)

        for key, value in record_extras(record).items():
            if key == "request_id":
                continue  # already handled above
            if key in _RESERVED_OUTPUT_KEYS:
                key = f"extra_{key}"
            data[key] = REDACTED if is_sensitive_key(key) else redact_value(value)

        return json.dumps(data, default=str, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Plain one-line format for local development (LOG_FORMAT=text)."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")

    def format(self, record: logging.LogRecord) -> str:  # noqa: D102
        base = super().format(record)
        extras = {
            k: (REDACTED if is_sensitive_key(k) else redact_value(v))
            for k, v in record_extras(record).items()
        }
        rid = get_request_id()
        if rid:
            extras.setdefault("request_id", rid)
        if extras:
            base = base + " " + " ".join(f"{k}={v!r}" for k, v in extras.items())
        return mask_emails(base)


def resolve_level() -> int:
    raw = os.getenv("LOG_LEVEL") or os.getenv("LOGS_LEVEL") or "INFO"
    raw = raw.strip().upper()
    if raw.isdigit():
        return int(raw)
    return logging.getLevelNamesMapping().get(raw, logging.INFO)


def configure_logging(service: str, env: str) -> logging.Handler:
    """Install (or refresh) the single stdout handler on the root logger."""
    root = logging.getLogger()
    fmt = (os.getenv("LOG_FORMAT") or "json").strip().lower()
    formatter: logging.Formatter = TextFormatter() if fmt == "text" else JsonFormatter(service, env)

    existing = [h for h in root.handlers if getattr(h, "name", None) == HANDLER_NAME]
    handler: logging.StreamHandler
    if existing:
        handler = existing[0]  # type: ignore[assignment]
    else:
        handler = logging.StreamHandler(sys.stdout)
        handler.set_name(HANDLER_NAME)
    handler.setStream(sys.stdout)
    handler.setFormatter(formatter)

    # Exactly one handler on root: ours. Anything else would duplicate lines.
    for h in list(root.handlers):
        if h is not handler:
            root.removeHandler(h)
    if handler not in root.handlers:
        root.addHandler(handler)

    root.setLevel(resolve_level())

    for name in NOISY_LOGGERS:
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True

    # RequestIDMiddleware already logs one structured "request" line per
    # request (and skips health probes), so uvicorn's access log is a
    # duplicate. Silence it unless UVICORN_ACCESS_LOG=1.
    if os.getenv("UVICORN_ACCESS_LOG", "").lower() not in ("1", "true", "yes"):
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    else:
        logging.getLogger("uvicorn.access").setLevel(logging.NOTSET)

    return handler
