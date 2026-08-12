"""Rate limiter tests.

The limiter is skipped inside the Flask test client (the suite would otherwise
fight a shared counter), so it is exercised directly here -- including through
the real endpoint with TESTING switched off, which is the only way to prove the
decorator is actually wired up.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from astrology import ratelimit  # noqa: E402


@pytest.fixture(autouse=True)
def clean():
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_requests_are_allowed_up_to_the_limit():
    for i in range(5):
        decision = ratelimit.check("b", "ip1", limit=5, window_seconds=60, now=1000)
        assert decision.allowed, f"request {i + 1} should be allowed"
        assert decision.remaining == 4 - i


def test_the_next_request_is_refused():
    for _ in range(5):
        ratelimit.check("b", "ip1", limit=5, window_seconds=60, now=1000)
    decision = ratelimit.check("b", "ip1", limit=5, window_seconds=60, now=1000)
    assert decision.allowed is False
    assert decision.remaining == 0
    assert 0 < decision.retry_after <= 61


def test_identities_are_counted_separately():
    for _ in range(5):
        ratelimit.check("b", "noisy", limit=5, window_seconds=60, now=1000)
    assert ratelimit.check("b", "noisy", limit=5, window_seconds=60, now=1000).allowed is False
    # A different caller is unaffected.
    assert ratelimit.check("b", "quiet", limit=5, window_seconds=60, now=1000).allowed is True


def test_buckets_are_counted_separately():
    for _ in range(5):
        ratelimit.check("reading", "ip1", limit=5, window_seconds=60, now=1000)
    assert ratelimit.check("reading", "ip1", limit=5, window_seconds=60, now=1000).allowed is False
    assert ratelimit.check("chart", "ip1", limit=5, window_seconds=60, now=1000).allowed is True


def test_the_window_resets():
    for _ in range(5):
        ratelimit.check("b", "ip1", limit=5, window_seconds=60, now=1000)
    assert ratelimit.check("b", "ip1", limit=5, window_seconds=60, now=1030).allowed is False
    # Once the window has fully elapsed, the caller starts fresh.
    assert ratelimit.check("b", "ip1", limit=5, window_seconds=60, now=1061).allowed is True


def test_retry_after_shrinks_as_the_window_elapses():
    for _ in range(2):
        ratelimit.check("b", "ip1", limit=2, window_seconds=60, now=1000)
    early = ratelimit.check("b", "ip1", limit=2, window_seconds=60, now=1005).retry_after
    late = ratelimit.check("b", "ip1", limit=2, window_seconds=60, now=1050).retry_after
    assert late < early


def test_missing_identity_does_not_collapse_into_a_shared_counter():
    """An unknown address still gets counted rather than crashing."""
    assert ratelimit.check("b", "", limit=1, window_seconds=60, now=1000).allowed is True
    assert ratelimit.check("b", "", limit=1, window_seconds=60, now=1000).allowed is False


def test_the_reading_endpoint_actually_enforces_its_limit(monkeypatch):
    """Proves the decorator is wired in, not just that the counter works."""
    import app as app_module

    monkeypatch.setitem(app_module.RATE_LIMITS, "reading", 2)
    app_module.app.config["TESTING"] = False
    client = app_module.app.test_client()

    birth = {
        "name": "Rate", "date": "1991-06-05", "time": "08:00", "timeKnown": True,
        "place": "Paris", "latitude": 48.8566, "longitude": 2.3522,
        "timezone": "Europe/Paris",
    }
    try:
        # Distinct charts so the reading cache cannot absorb them.
        codes = [
            client.post("/api/reading", json={**birth, "name": f"Rate{i}"}).status_code
            for i in range(4)
        ]
        assert codes[:2] == [200, 200]
        assert codes[2:] == [429, 429]

        refused = client.post("/api/reading", json={**birth, "name": "RateX"})
        assert refused.headers["Retry-After"]
        assert "requests" in refused.get_json()["error"]
    finally:
        app_module.app.config["TESTING"] = True


def test_a_cached_reading_does_not_spend_the_limit(monkeypatch):
    """Refreshing the same reading must stay free -- that is the cost fix."""
    import app as app_module

    monkeypatch.setitem(app_module.RATE_LIMITS, "reading", 2)
    app_module.app.config["TESTING"] = False
    app_module._reading_cache.clear()
    client = app_module.app.test_client()

    birth = {
        "name": "Cached", "date": "1988-02-19", "time": "22:10", "timeKnown": True,
        "place": "Berlin", "latitude": 52.52, "longitude": 13.405,
        "timezone": "Europe/Berlin",
    }
    try:
        first = client.post("/api/reading", json=birth)
        assert first.status_code == 200
        assert first.get_json()["cached"] is False

        # Ten refreshes of the same chart, well past the limit of two.
        for _ in range(10):
            repeat = client.post("/api/reading", json=birth)
            assert repeat.status_code == 200
            assert repeat.get_json()["cached"] is True
    finally:
        app_module.app.config["TESTING"] = True
