from __future__ import annotations

import logging
import re

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rexbrown_observability import (
    RequestIDMiddleware,
    get_request_id,
    httpx_event_hook,
    inject_request_id,
    outgoing_headers,
    request_id_var,
    setup,
)

HEX32 = re.compile(r"^[0-9a-f]{32}$")


def make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/items")
    def items():
        logging.getLogger("app").info("handling", extra={"order_id": 5})
        return {"rid": get_request_id()}

    @app.get("/boom")
    def boom():
        raise RuntimeError("bad")

    return app


def test_echoes_valid_incoming_id(json_lines):
    app = make_app()
    setup(app, service="svc")
    client = TestClient(app)
    r = client.get("/items", headers={"X-Request-ID": "req-1.abc_XYZ"})
    assert r.status_code == 200
    assert r.headers["x-request-id"] == "req-1.abc_XYZ"
    assert r.json()["rid"] == "req-1.abc_XYZ"


def test_generates_id_when_missing(json_lines):
    app = make_app()
    setup(app, service="svc")
    r = TestClient(app).get("/items")
    assert HEX32.match(r.headers["x-request-id"])
    assert r.json()["rid"] == r.headers["x-request-id"]


@pytest.mark.parametrize("bad", ["", "a" * 129, "has space", "semi;colon", "slash/x", "<script>"])
def test_rejects_invalid_incoming_id(bad, json_lines):
    app = make_app()
    setup(app, service="svc")
    r = TestClient(app).get("/items", headers={"X-Request-ID": bad})
    assert HEX32.match(r.headers["x-request-id"])
    assert r.headers["x-request-id"] != bad


@pytest.mark.parametrize("bad", ["héllo", "a" * 129, None, "", "x y"])
def test_resolve_request_id_rejects(bad):
    from rexbrown_observability.context import resolve_request_id

    assert HEX32.match(resolve_request_id(bad))


def test_resolve_request_id_accepts_valid():
    from rexbrown_observability.context import resolve_request_id

    assert resolve_request_id("a" * 128) == "a" * 128
    assert resolve_request_id("A-b.c_9") == "A-b.c_9"


def test_request_log_line_and_request_id_in_app_logs(json_lines):
    app = make_app()
    setup(app, service="svc")
    TestClient(app).get("/items?x=1", headers={"X-Request-ID": "rid42"})
    lines = json_lines()
    app_line = next(l for l in lines if l["logger"] == "app")
    http_line = next(l for l in lines if l["logger"] == "http")
    assert app_line["request_id"] == "rid42"
    assert app_line["order_id"] == 5
    assert http_line["msg"] == "request"
    assert http_line["request_id"] == "rid42"
    assert http_line["method"] == "GET"
    assert http_line["path"] == "/items"
    assert http_line["status"] == 200
    assert isinstance(http_line["duration_ms"], (int, float))
    assert http_line["level"] == "INFO"


def test_health_paths_not_logged(json_lines):
    app = make_app()
    setup(app, service="svc", extra_health_paths=["/healthz"])
    client = TestClient(app)
    client.get("/health")
    client.get("/healthz")
    assert [l for l in json_lines() if l["logger"] == "http"] == []


def test_unhandled_exception_logs_500(json_lines):
    app = make_app()
    setup(app, service="svc")
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500
    http_line = next(l for l in json_lines() if l["logger"] == "http")
    assert http_line["status"] == 500


def test_contextvar_reset_after_request(json_lines):
    app = make_app()
    setup(app, service="svc")
    TestClient(app).get("/items", headers={"X-Request-ID": "abc"})
    assert get_request_id() is None


def test_middleware_not_duplicated_on_repeat_setup(json_lines):
    app = make_app()
    setup(app, service="svc")
    setup(app, service="svc")
    count = sum(1 for m in app.user_middleware if m.cls is RequestIDMiddleware)
    assert count == 1
    lines_before = len(json_lines())
    TestClient(app).get("/items")
    http_lines = [l for l in json_lines() if l["logger"] == "http"]
    assert len(http_lines) == 1 and lines_before == 0


def test_outgoing_headers_and_inject():
    assert outgoing_headers() == {}
    token = request_id_var.set("outbound1")
    try:
        assert outgoing_headers() == {"X-Request-ID": "outbound1"}
        merged = outgoing_headers({"Accept": "application/json"})
        assert merged == {"Accept": "application/json", "X-Request-ID": "outbound1"}
        existing = {"x-request-id": "keep"}
        assert inject_request_id(existing) == {"x-request-id": "keep"}
        h: dict = {}
        inject_request_id(h)
        assert h == {"X-Request-ID": "outbound1"}
    finally:
        request_id_var.reset(token)


def test_httpx_event_hook():
    token = request_id_var.set("hx1")
    try:
        req = httpx.Request("GET", "http://example.invalid/")
        httpx_event_hook(req)
        assert req.headers["x-request-id"] == "hx1"
    finally:
        request_id_var.reset(token)


def test_middleware_passes_through_non_http():
    seen = {}

    async def inner(scope, receive, send):
        seen["type"] = scope["type"]

    mw = RequestIDMiddleware(inner)
    import asyncio

    asyncio.run(mw({"type": "lifespan"}, None, None))
    assert seen["type"] == "lifespan"
