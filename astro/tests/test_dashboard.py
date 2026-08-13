"""Dashboard tests.

Two things matter most here and both are about honesty rather than layout:
the free tier must not receive locked timing data at all, and the "systems"
section must only ever describe data we genuinely compute.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ.setdefault("ASTRO_DB_PATH", _tmp.name)
os.environ.setdefault("WHOP_WEBHOOK_SECRET", "test-webhook-secret")

from astrology import dashboard, entitlements  # noqa: E402

SECRET = os.environ["WHOP_WEBHOOK_SECRET"]

TIMED = {
    "name": "Robin",
    "date": "1990-12-03",
    "time": "16:20",
    "timeKnown": True,
    "place": "Dublin, Ireland",
    "latitude": 53.3331,
    "longitude": -6.2489,
    "timezone": "Europe/Dublin",
}

UNTIMED = {
    "name": "Sam",
    "date": "1997-03-12",
    "timeKnown": False,
    "place": "New York City, New York, United States",
    "latitude": 40.7143,
    "longitude": -74.006,
    "timezone": "America/New_York",
}


@pytest.fixture(autouse=True)
def clean_store():
    entitlements.init()
    entitlements.reset_for_tests()
    yield
    entitlements.reset_for_tests()


@pytest.fixture
def client():
    from app import app

    app.config["TESTING"] = True
    return app.test_client()


def make_paid(client):
    """Give this client's session a live membership."""
    client.get("/")
    sid = client.get_cookie(entitlements.COOKIE_NAME).value
    payload = {
        "event": "membership.went_valid",
        "data": {"id": "mem_dash", "status": "active", "metadata": {"sid": sid}},
    }
    raw = json.dumps(payload).encode()
    signature = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    response = client.post(
        "/api/whop/webhook",
        data=raw,
        headers={"Content-Type": "application/json", "X-Whop-Signature": signature},
    )
    assert response.status_code == 200
    return sid


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


def test_dashboard_returns_every_section(client):
    body = client.post("/api/dashboard", json=TIMED).get_json()
    for key in ("archetype", "systems", "tabs", "timing", "precision", "tier"):
        assert key in body, key

    assert body["archetype"]["name"]
    assert body["archetype"]["line"]
    assert body["systems"]
    assert body["timing"]


def test_the_four_tabs_are_present_and_populated(client):
    body = client.post("/api/dashboard", json=TIMED).get_json()
    assert [t["label"] for t in body["tabs"]] == [
        "Who You Are", "How You Operate", "Strengths", "Blind Spots",
    ]
    for tab in body["tabs"]:
        assert tab["content"], f"{tab['label']} is empty"


def test_who_you_are_and_how_you_operate_are_different_text(client):
    """Two tabs sharing one paragraph would be padding, not structure."""
    body = client.post("/api/dashboard", json=TIMED).get_json()
    by_key = {t["key"]: t["content"] for t in body["tabs"]}
    assert by_key["identity"] != by_key["operating"]


def test_archetype_varies_between_charts(client):
    a = client.post("/api/dashboard", json=TIMED).get_json()["archetype"]["name"]
    b = client.post("/api/dashboard", json={
        **TIMED, "name": "Kit", "date": "2001-01-17", "time": "19:45",
        "place": "Santiago", "latitude": -33.4569, "longitude": -70.6483,
        "timezone": "America/Santiago",
    }).get_json()["archetype"]["name"]
    assert a != b


# ---------------------------------------------------------------------------
# Systems: only what we actually compute
# ---------------------------------------------------------------------------


def test_systems_do_not_claim_engines_we_do_not_have(client):
    """The dashboard must not imply a numerology or Human Design engine."""
    body = client.post("/api/dashboard", json=TIMED).get_json()
    blob = json.dumps(body["systems"]).lower()
    for invented in ("numerolog", "human design", "enneagram", "tarot",
                     "myers", "gene key", "vedic", "bazi"):
        assert invented not in blob, f"claims a system we never built: {invented}"


def test_every_system_card_has_a_real_read(client):
    body = client.post("/api/dashboard", json=TIMED).get_json()
    for card in body["systems"]:
        assert card["name"] and card["source"]
        assert len(card["read"]) > 40, f"{card['name']} has a stub read"
        assert card["status"] in ("ready", "needs_time")


def test_house_layer_is_switched_off_without_a_birth_time(client):
    body = client.post("/api/dashboard", json=UNTIMED).get_json()
    houses = next(c for c in body["systems"] if c["key"] == "houses")
    assert houses["status"] == "needs_time"
    assert houses["more"] == "time"

    # And nothing house-derived leaks into the card.
    assert "midheaven —" not in houses["read"].lower()


def test_house_layer_is_live_with_a_birth_time(client):
    body = client.post("/api/dashboard", json=TIMED).get_json()
    houses = next(c for c in body["systems"] if c["key"] == "houses")
    assert houses["status"] == "ready"
    assert "Midheaven" in houses["read"]
    assert not [c for c in body["systems"] if c["status"] == "needs_time"]


# ---------------------------------------------------------------------------
# Birth-time precision
# ---------------------------------------------------------------------------


def test_precision_is_silent_when_the_time_is_known(client):
    body = client.post("/api/dashboard", json=TIMED).get_json()
    assert body["precision"] == {"exact": True}


def test_missing_time_reads_as_an_upgrade_not_an_error(client):
    body = client.post("/api/dashboard", json=UNTIMED).get_json()
    precision = body["precision"]

    assert precision["exact"] is False
    assert precision["cta"]
    assert len(precision["unlocks"]) >= 3

    # No blame, no alarm -- this is an offer, not a validation failure.
    text = f"{precision['headline']} {precision['body']} {precision['note']}".lower()
    for scolding in ("error", "invalid", "missing data", "you must", "required",
                     "failed", "warning", "incomplete"):
        assert scolding not in text, f"reads as an error: {scolding!r}"

    # And it says plainly that the rest is still exact.
    assert "exactly" in precision["body"]


# ---------------------------------------------------------------------------
# Timing: the free/paid cut
# ---------------------------------------------------------------------------


def test_free_tier_gets_three_locked_buckets_with_real_teasers(client):
    body = client.post("/api/dashboard", json=TIMED).get_json()
    buckets = body["timing"]

    assert [b["label"] for b in buckets] == ["Today", "This week", "This month"]
    for bucket in buckets:
        assert bucket["locked"] is True
        assert "entries" not in bucket, "locked window data must not be sent"
        # A locked box that says nothing reads as an empty box.
        assert len(bucket["teaser"]) > 20, f"{bucket['label']} has no teaser"
        assert bucket["count"] >= 0


def test_no_window_detail_reaches_a_free_client(client):
    """The cut is in the payload, so there is nothing to reveal with devtools."""
    raw = client.post("/api/dashboard", json=TIMED).get_data(as_text=True).lower()
    # Aspect names only ever appear inside a window entry.
    for leak in ("conjunction", "opposition", "trine", "square", "sextile"):
        assert leak not in raw, f"free payload leaked window detail: {leak}"


def test_paid_tier_gets_the_windows_themselves(client):
    make_paid(client)
    body = client.post("/api/dashboard", json=TIMED).get_json()

    assert body["tier"] == "paid"
    for bucket in body["timing"]:
        assert bucket["locked"] is False
        assert "entries" in bucket
        assert len(bucket["entries"]) == bucket["count"]

    entries = [e for b in body["timing"] for e in b["entries"]]
    assert entries, "a paid dashboard with no windows at all is suspicious"
    for entry in entries:
        assert entry["title"] and entry["dates"]


def test_buckets_answer_different_questions(client):
    """Today, this week and this month must not be three copies of one list."""
    make_paid(client)
    body = client.post("/api/dashboard", json=TIMED).get_json()
    counts = [b["count"] for b in body["timing"]]
    assert len(set(counts)) > 1, f"buckets are indistinguishable: {counts}"


def test_total_windows_is_not_the_sum_of_the_buckets(client):
    """The buckets overlap, so summing them would overstate the real figure."""
    body = client.post("/api/dashboard", json=TIMED).get_json()
    assert body["totalWindows"] >= max(b["count"] for b in body["timing"])


def test_an_already_running_window_does_not_count_as_opening_today():
    """The transit scan clamps running windows to today; that is not an event."""
    today = dt.date.today()
    timing = {
        "windows": [{
            "transiting": "Saturn", "aspect": "conjunction", "natal_point": "Sun",
            "start": today.isoformat(),                       # clamped, not new
            "end": (today + dt.timedelta(days=300)).isoformat(),
            "exact_dates": [], "perfects": False, "activeNow": True,
            "meaning": "x",
        }],
        "cycles": [], "mercuryRetrograde": [],
    }
    buckets = {b["key"]: b for b in dashboard.timing_buckets(timing, "paid")}
    assert buckets["today"]["count"] == 1     # it is in effect
    assert buckets["week"]["count"] == 0      # but nothing changes
    assert buckets["month"]["count"] == 0


def test_a_window_perfecting_soon_shows_up_in_the_right_bucket():
    today = dt.date.today()
    timing = {
        "windows": [{
            "transiting": "Jupiter", "aspect": "trine", "natal_point": "Midheaven",
            "start": (today - dt.timedelta(days=10)).isoformat(),
            "end": (today + dt.timedelta(days=60)).isoformat(),
            "exact_dates": [(today + dt.timedelta(days=3)).isoformat()],
            "perfects": True, "activeNow": True, "meaning": "x",
        }],
        "cycles": [], "mercuryRetrograde": [],
    }
    buckets = {b["key"]: b for b in dashboard.timing_buckets(timing, "paid")}
    assert buckets["week"]["count"] == 1
    assert buckets["week"]["exactCount"] == 1
    assert "exact" in buckets["week"]["teaser"]


def test_an_empty_bucket_still_says_something_useful():
    timing = {"windows": [], "cycles": [], "mercuryRetrograde": []}
    for bucket in dashboard.timing_buckets(timing, "free"):
        assert bucket["count"] == 0
        assert len(bucket["teaser"]) > 20
        assert "undefined" not in bucket["teaser"].lower()


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def test_dashboard_and_reading_share_one_generation(client):
    """Landing on the dashboard then opening the full chart must not bill twice."""
    first = client.post("/api/dashboard", json=TIMED)
    assert first.status_code == 200

    reading = client.post("/api/reading", json=TIMED).get_json()
    assert reading["cached"] is True, "the full chart re-generated the reading"
