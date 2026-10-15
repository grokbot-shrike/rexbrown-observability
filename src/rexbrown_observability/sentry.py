"""Optional Sentry / GlitchTip initialisation. The SDK is only imported when a DSN is set."""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
_active = False


def sentry_dsn() -> str | None:
    for var in ("SENTRY_DSN", "GLITCHTIP_DSN"):
        value = (os.getenv(var) or "").strip()
        if value:
            return value
    return None


def is_active() -> bool:
    return _active


def init_sentry(*, service: str, env: str, version: str) -> bool:
    """Initialise sentry-sdk if a DSN is configured. Returns True when active."""
    global _active
    dsn = sentry_dsn()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        log.warning(
            "sentry dsn set but sentry-sdk is not installed; install rexbrown-observability[sentry]"
        )
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=env,
        release=version,
        send_default_pii=False,
        traces_sample_rate=0.0,
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
    )
    sentry_sdk.set_tag("service", service)
    _active = True
    return True
