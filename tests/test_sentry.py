from __future__ import annotations

import builtins
import logging
import sys
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rexbrown_observability import sentry_is_active, setup


def test_sentry_not_initialised_without_dsn(json_lines):
    with mock.patch("sentry_sdk.init") as init:
        setup(service="svc")
        init.assert_not_called()
    assert sentry_is_active() is False


def test_sentry_not_initialised_with_blank_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "   ")
    with mock.patch("sentry_sdk.init") as init:
        setup(service="svc")
        init.assert_not_called()
    assert sentry_is_active() is False


@pytest.mark.parametrize("var", ["SENTRY_DSN", "GLITCHTIP_DSN"])
def test_sentry_init_with_dsn(monkeypatch, var, json_lines):
    monkeypatch.setenv(var, "https://key@glitchtip.example/1")
    monkeypatch.setenv("ENV", "prod")
    from sentry_sdk.integrations.logging import LoggingIntegration

    with mock.patch("sentry_sdk.init") as init, mock.patch("sentry_sdk.set_tag") as set_tag:
        setup(service="vigil-api", version="2.3.4")
        init.assert_called_once()
        kwargs = init.call_args.kwargs
        assert kwargs["dsn"] == "https://key@glitchtip.example/1"
        assert kwargs["environment"] == "prod"
        assert kwargs["release"] == "2.3.4"
        assert kwargs["send_default_pii"] is False
        assert kwargs["traces_sample_rate"] == 0
        (integration,) = kwargs["integrations"]
        assert isinstance(integration, LoggingIntegration)
        assert integration._handler.level == logging.ERROR  # event_level
        assert integration._breadcrumb_handler.level == logging.INFO
        set_tag.assert_called_once_with("service", "vigil-api")
    assert sentry_is_active() is True


def test_middleware_sets_request_id_tag_when_sentry_active(monkeypatch, json_lines):
    monkeypatch.setenv("SENTRY_DSN", "https://key@glitchtip.example/1")
    app = FastAPI()

    @app.get("/x")
    def x():
        return {}

    with mock.patch("sentry_sdk.init"), mock.patch("sentry_sdk.set_tag") as set_tag:
        setup(app, service="svc")
        TestClient(app).get("/x", headers={"X-Request-ID": "tagme"})
        assert mock.call("request_id", "tagme") in set_tag.call_args_list


def test_middleware_does_not_touch_sentry_when_inactive(json_lines):
    app = FastAPI()

    @app.get("/x")
    def x():
        return {}

    with mock.patch("sentry_sdk.set_tag") as set_tag:
        setup(app, service="svc")
        TestClient(app).get("/x")
        set_tag.assert_not_called()


def test_sentry_missing_sdk_logs_warning(monkeypatch, json_lines):
    monkeypatch.setenv("SENTRY_DSN", "https://key@glitchtip.example/1")
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentry_sdk" or name.startswith("sentry_sdk."):
            raise ImportError("No module named 'sentry_sdk'")
        return real_import(name, *args, **kwargs)

    for mod in [m for m in sys.modules if m == "sentry_sdk" or m.startswith("sentry_sdk.")]:
        monkeypatch.delitem(sys.modules, mod)
    with mock.patch.object(builtins, "__import__", side_effect=fake_import):
        setup(service="svc")
    warn = next(l for l in json_lines() if l["level"] == "WARNING")
    assert "sentry-sdk is not installed" in warn["msg"]
    assert sentry_is_active() is False
