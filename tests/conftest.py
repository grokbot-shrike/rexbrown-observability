from __future__ import annotations

import json
import logging

import pytest

from rexbrown_observability import logging_setup, sentry
from rexbrown_observability.context import request_id_var


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("ENV", "LOG_LEVEL", "LOGS_LEVEL", "LOG_FORMAT", "SENTRY_DSN", "GLITCHTIP_DSN", "APP_VERSION"):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture(autouse=True)
def _reset_logging():
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved = {n: (list(logging.getLogger(n).handlers), logging.getLogger(n).propagate)
             for n in logging_setup.NOISY_LOGGERS}
    sentry._active = False
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)
    for n, (handlers, propagate) in saved.items():
        logging.getLogger(n).handlers[:] = handlers
        logging.getLogger(n).propagate = propagate
    request_id_var.set(None)
    sentry._active = False


def parse_lines(out: str) -> list[dict]:
    return [json.loads(line) for line in out.splitlines() if line.strip()]


@pytest.fixture
def json_lines(capsys):
    """Return a callable that reads captured stdout and parses each JSON line."""

    def _read() -> list[dict]:
        return parse_lines(capsys.readouterr().out)

    return _read
