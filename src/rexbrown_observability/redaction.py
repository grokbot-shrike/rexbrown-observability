"""Redaction of secrets and PII from log fields and messages."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_SUBSTRINGS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "cookie",
    "email",
)

# Short names matched only as whole snake/kebab-case segments, so that
# e.g. ``shipping_id`` or ``mapping`` are not redacted but ``pin``/``user_pin``
# and ``sentry_dsn`` are.
SENSITIVE_SEGMENTS: frozenset[str] = frozenset({"pin", "dsn"})

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def is_sensitive_key(key: Any) -> bool:
    """True if the key name matches any sensitive substring (case-insensitive)."""
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    if any(s in lowered for s in SENSITIVE_SUBSTRINGS):
        return True
    return any(seg in SENSITIVE_SEGMENTS for seg in re.split(r"[_\-.]", lowered))


def redact_value(value: Any) -> Any:
    """Recursively redact sensitive keys inside dicts (and lists of dicts)."""
    if isinstance(value, dict):
        return {
            k: (REDACTED if is_sensitive_key(k) else redact_value(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(redact_value(v) for v in value)
    return value


def redact_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Redact a flat/nested mapping of log fields."""
    return redact_value(fields)


def mask_emails(text: str) -> str:
    """Replace any email address in free text with the redaction marker."""
    if "@" not in text:
        return text
    return EMAIL_RE.sub(REDACTED, text)
