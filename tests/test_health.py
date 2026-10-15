from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from rexbrown_observability import setup


def test_health_ok_with_defaults(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    app = FastAPI()
    setup(app, service="svc")
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "svc", "version": "9.9.9", "checks": {}}
    assert "x-request-id" in r.headers


def test_version_unknown_when_unset():
    app = FastAPI()
    setup(app, service="svc")
    assert TestClient(app).get("/health").json()["version"] == "unknown"


def test_health_sync_and_async_checks_ok():
    async def async_ok():
        await asyncio.sleep(0)
        return True

    app = FastAPI()
    setup(app, service="svc", version="1.0", health_checks={"db": lambda: True, "cache": async_ok})
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["checks"] == {"db": "ok", "cache": "ok"}
    assert r.json()["version"] == "1.0"


def test_health_degraded_on_exception_and_false(json_lines):
    def dead():
        raise ConnectionError("db down")

    async def async_false():
        return False

    app = FastAPI()
    setup(app, service="svc", health_checks={"db": dead, "mq": async_false, "fs": lambda: None})
    r = TestClient(app).get("/health")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"] == {"db": "error", "mq": "error", "fs": "ok"}
    warn = next(l for l in json_lines() if l["level"] == "WARNING")
    assert warn["check"] == "db"
    assert "ConnectionError" in warn["exc_info"]


def test_extra_health_paths_registered():
    app = FastAPI()
    setup(app, service="svc", health_path="/orders/health", extra_health_paths=("/healthz", "/go/online"))
    client = TestClient(app)
    for path in ("/orders/health", "/healthz", "/go/online"):
        assert client.get(path).status_code == 200, path
    assert client.get("/health").status_code == 404


def test_does_not_overwrite_existing_route():
    app = FastAPI()

    @app.get("/health")
    def mine():
        return {"custom": True}

    setup(app, service="svc")
    r = TestClient(app).get("/health")
    assert r.json() == {"custom": True}
    assert sum(1 for route in app.routes if getattr(route, "path", None) == "/health") == 1
