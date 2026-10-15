

def test_short_segments_do_not_overmatch():
    from rexbrown_observability.redaction import is_sensitive_key
    assert is_sensitive_key("pin") and is_sensitive_key("user_pin") and is_sensitive_key("SENTRY_DSN")
    assert not is_sensitive_key("shipping_id") and not is_sensitive_key("mapping")
