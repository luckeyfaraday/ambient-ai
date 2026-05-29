from __future__ import annotations

from ambient_ai.events import AmbientEvent, make_fingerprint


def test_fingerprint_deterministic():
    event = AmbientEvent(source="browser", kind="tab", title="Hello World")
    assert make_fingerprint(event) == make_fingerprint(event)


def test_fingerprint_case_insensitive():
    a = AmbientEvent(source="browser", kind="tab", title="Hello World")
    b = AmbientEvent(source="browser", kind="tab", title="hello world")
    assert make_fingerprint(a) == make_fingerprint(b)


def test_fingerprint_includes_url():
    a = AmbientEvent(source="browser", kind="tab", title="X", url="https://a.com")
    b = AmbientEvent(source="browser", kind="tab", title="X", url="https://b.com")
    assert make_fingerprint(a) != make_fingerprint(b)


def test_fingerprint_different_source():
    a = AmbientEvent(source="browser", kind="tab", title="X")
    b = AmbientEvent(source="app", kind="tab", title="X")
    assert make_fingerprint(a) != make_fingerprint(b)


def test_fingerprint_different_kind():
    a = AmbientEvent(source="browser", kind="tab", title="X")
    b = AmbientEvent(source="browser", kind="bookmark", title="X")
    assert make_fingerprint(a) != make_fingerprint(b)


def test_fingerprint_is_digest():
    long_title = "x" * 1000
    event = AmbientEvent(source="browser", kind="tab", title=long_title)
    assert len(make_fingerprint(event)) == 64


def test_fingerprint_uses_full_key_before_hashing():
    prefix = "x" * 600
    a = AmbientEvent(source="browser", kind="tab", title=f"{prefix}a")
    b = AmbientEvent(source="browser", kind="tab", title=f"{prefix}b")
    assert make_fingerprint(a) != make_fingerprint(b)


def test_fingerprint_no_url_matches_empty():
    a = AmbientEvent(source="browser", kind="tab", title="X", url=None)
    b = AmbientEvent(source="browser", kind="tab", title="X")
    assert make_fingerprint(a) == make_fingerprint(b)
