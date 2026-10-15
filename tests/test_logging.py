from __future__ import annotations

import logging
import re

from rexbrown_observability import logging_setup, setup
from rexbrown_observability.context import request_id_var

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def test_json_fields_and_microseconds(json_lines, monkeypatch):
    monkeypatch.setenv("ENV", "staging")
    setup(service="pickflow")
    logging.getLogger("tests.mod").info("hello")
    (rec,) = json_lines()
    assert TS_RE.match(rec["ts"]), rec["ts"]
    assert rec["level"] == "INFO"
    assert rec["service"] == "pickflow"
    assert rec["env"] == "staging"
    assert rec["logger"] == "tests.mod"
    assert rec["msg"] == "hello"
    assert rec["file"].endswith("test_logging.py")
    assert isinstance(rec["line"], int)
    assert "request_id" not in rec
    assert "exc_info" not in rec


def test_env_defaults_to_dev(json_lines):
    setup(service="svc")
    logging.getLogger("x").info("m")
    assert json_lines()[0]["env"] == "dev"


def test_extras_merged(json_lines):
    setup(service="svc")
    logging.getLogger("x").info(
        "order picked", extra={"order_id": 42, "employee_id": "e9", "channel_id": "c1", "nested": {"a": 1}}
    )
    (rec,) = json_lines()
    assert rec["order_id"] == 42
    assert rec["employee_id"] == "e9"
    assert rec["channel_id"] == "c1"
    assert rec["nested"] == {"a": 1}


def test_extra_non_serialisable_uses_default_str(json_lines):
    import datetime

    setup(service="svc")
    logging.getLogger("x").info("m", extra={"when": datetime.date(2026, 1, 2)})
    assert json_lines()[0]["when"] == "2026-01-02"


def test_request_id_from_contextvar(json_lines):
    setup(service="svc")
    token = request_id_var.set("abc123")
    try:
        logging.getLogger("x").info("m")
    finally:
        request_id_var.reset(token)
    assert json_lines()[0]["request_id"] == "abc123"


def test_traceback_in_exc_info(json_lines):
    setup(service="svc")
    log = logging.getLogger("x")
    try:
        1 / 0
    except ZeroDivisionError:
        log.exception("boom", extra={"order_id": 1})
    (rec,) = json_lines()
    assert rec["level"] == "ERROR"
    assert rec["msg"] == "boom"
    assert "Traceback (most recent call last)" in rec["exc_info"]
    assert "ZeroDivisionError" in rec["exc_info"]
    assert rec["order_id"] == 1


def test_redaction_of_sensitive_keys(json_lines):
    setup(service="svc")
    logging.getLogger("x").info(
        "m",
        extra={
            "password": "p",
            "Passwd": "p",
            "client_secret": "s",
            "access_token": "t",
            "Authorization": "Bearer x",
            "api_key": "k",
            "ApiKey": "k",
            "cookie": "c",
            "SENTRY_DSN": "d",
            "user_email": "a@b.com",
            "pin": "1234",
            "ok_field": "visible",
            "cfg": {"db": {"password": "x", "host": "h"}, "list": [{"token": "t"}]},
        },
    )
    (rec,) = json_lines()
    for key in (
        "password", "Passwd", "client_secret", "access_token", "Authorization",
        "api_key", "ApiKey", "cookie", "SENTRY_DSN", "user_email", "pin",
    ):
        assert rec[key] == "[REDACTED]", key
    assert rec["ok_field"] == "visible"
    assert rec["cfg"] == {"db": {"password": "[REDACTED]", "host": "h"}, "list": [{"token": "[REDACTED]"}]}


def test_email_masked_in_message(json_lines):
    setup(service="svc")
    logging.getLogger("x").info("login for ross.smith+x@example.co.uk failed")
    assert json_lines()[0]["msg"] == "login for [REDACTED] failed"


def test_uvicorn_and_huey_loggers_propagate_to_root(json_lines):
    for name in logging_setup.NOISY_LOGGERS:
        lg = logging.getLogger(name)
        lg.addHandler(logging.NullHandler())
        lg.propagate = False
    setup(service="svc")
    for name in logging_setup.NOISY_LOGGERS:
        lg = logging.getLogger(name)
        assert lg.handlers == []
        assert lg.propagate is True
    logging.getLogger("uvicorn.error").info("GET /")
    (rec,) = json_lines()
    assert rec["logger"] == "uvicorn.error"


def test_idempotent(json_lines):
    setup(service="svc")
    setup(service="svc")
    setup(service="svc")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    logging.getLogger("x").info("once")
    assert len(json_lines()) == 1


def test_log_level_env(json_lines, monkeypatch):
    monkeypatch.setenv("LOGS_LEVEL", "WARNING")
    setup(service="svc")
    assert logging.getLogger().level == logging.WARNING
    monkeypatch.setenv("LOG_LEVEL", "debug")
    setup(service="svc")
    assert logging.getLogger().level == logging.DEBUG


def test_default_level_is_info():
    setup(service="svc")
    assert logging.getLogger().level == logging.INFO


def test_text_format(capsys, monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "text")
    setup(service="svc")
    logging.getLogger("x").warning("plain line", extra={"order_id": 7, "token": "t"})
    out = capsys.readouterr().out.strip()
    assert not out.startswith("{")
    assert "WARNING x plain line" in out
    assert "order_id=7" in out
    assert "'[REDACTED]'" in out and "'t'" not in out


def test_color_message_dropped_and_access_log_quiet(monkeypatch):
    import io, json, logging
    from rexbrown_observability.logging_setup import JsonFormatter, configure_logging
    monkeypatch.delenv("UVICORN_ACCESS_LOG", raising=False)
    configure_logging(service="t", env="dev")
    assert logging.getLogger("uvicorn.access").getEffectiveLevel() == logging.WARNING
    rec = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, "hi", None, None)
    rec.color_message = "\x1b[36mhi\x1b[0m"
    assert "color_message" not in json.loads(JsonFormatter("t", "dev").format(rec))
