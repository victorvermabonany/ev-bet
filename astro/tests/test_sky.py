"""Live-sky tests.

The landing page states things about today as fact, so these check the numbers
against **external** references rather than against the module's own output:
published new and full moon instants, and published Mercury retrograde periods.
The rest guard the thing the brand cannot afford -- that nothing on that widget
is invented when the data is missing.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys

import pytest
import swisseph as swe

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from astrology import ephemeris as eph  # noqa: E402
from astrology import sky  # noqa: E402


def phase_at(moment: dt.datetime) -> dict:
    jd = eph.julian_day(moment)
    return sky.moon_phase(eph.raw(jd, swe.SUN)[0], eph.raw(jd, swe.MOON)[0])


# ---------------------------------------------------------------------------
# Moon phase, against published lunation times
# ---------------------------------------------------------------------------

NEW_MOONS = [
    dt.datetime(2024, 1, 11, 11, 57, tzinfo=dt.timezone.utc),
    dt.datetime(2025, 1, 29, 12, 36, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 1, 18, 19, 52, tzinfo=dt.timezone.utc),
]

FULL_MOONS = [
    dt.datetime(2024, 1, 25, 17, 54, tzinfo=dt.timezone.utc),
    dt.datetime(2025, 1, 13, 22, 27, tzinfo=dt.timezone.utc),
    dt.datetime(2026, 1, 3, 10, 3, tzinfo=dt.timezone.utc),
]


@pytest.mark.parametrize("moment", NEW_MOONS)
def test_new_moons_match_published_times(moment):
    phase = phase_at(moment)
    assert phase["name"] == "New Moon"
    assert phase["illuminationPercent"] == 0
    # Elongation folds to 0/360 at conjunction; either end is within a degree.
    assert min(phase["elongation"], 360 - phase["elongation"]) < 1.0


@pytest.mark.parametrize("moment", FULL_MOONS)
def test_full_moons_match_published_times(moment):
    phase = phase_at(moment)
    assert phase["name"] == "Full Moon"
    assert phase["illuminationPercent"] == 100
    assert abs(phase["elongation"] - 180.0) < 1.0


def test_quarters_are_half_lit():
    """A quarter moon is 50% lit by definition -- the geometry check."""
    for elongation, name, waxing in [(90.0, "First quarter", True),
                                     (270.0, "Last quarter", False)]:
        phase = sky.moon_phase(0.0, elongation)
        assert phase["name"] == name
        assert phase["illuminationPercent"] == 50
        assert phase["waxing"] is waxing


def test_illumination_climbs_and_falls_across_one_lunation():
    """Waxing means more light each day; waning means less."""
    start = NEW_MOONS[-1]
    daily = [phase_at(start + dt.timedelta(days=d))["illumination"] for d in range(30)]
    peak = daily.index(max(daily))
    assert daily[:peak] == sorted(daily[:peak]), "should climb to full"
    assert daily[peak:] == sorted(daily[peak:], reverse=True), "should fall after full"
    assert max(daily) > 0.98 and min(daily) < 0.02


# ---------------------------------------------------------------------------
# The moon graphic is drawn from the number, not picked from a sprite sheet
# ---------------------------------------------------------------------------

def test_moon_path_is_derived_from_illumination():
    """The terminator's semi-minor axis is r*|1-2k|, so it collapses at half."""
    quarter = sky.moon_path(0.5, True, radius=12)
    assert "A 0.000 12" in quarter, "a half-lit disc has a straight terminator"

    for k in (0.0, 1.0):
        assert "A 12.000 12" in sky.moon_path(k, True, radius=12)


def test_new_and_full_moons_do_not_render_identically():
    """The bug this guards: inverted sweep flags swap new and full."""
    assert sky.moon_path(0.0, True) != sky.moon_path(1.0, True)


def test_waxing_and_waning_mirror_each_other():
    assert sky.moon_path(0.3, True) != sky.moon_path(0.3, False)


# ---------------------------------------------------------------------------
# Mercury, against published retrograde periods
# ---------------------------------------------------------------------------

# Published 2025 Mercury retrograde periods (UTC).
MERCURY_RX_2025 = [
    (dt.date(2025, 3, 15), dt.date(2025, 4, 7)),
    (dt.date(2025, 7, 18), dt.date(2025, 8, 11)),
    (dt.date(2025, 11, 9), dt.date(2025, 11, 29)),
]


@pytest.mark.parametrize("start,end", MERCURY_RX_2025)
def test_mercury_is_retrograde_inside_published_windows(start, end):
    """Midway through a published window Mercury must read retrograde."""
    midpoint = start + (end - start) / 2
    moment = dt.datetime.combine(midpoint, dt.time(12, 0), tzinfo=dt.timezone.utc)
    position = eph.position(eph.julian_day(moment), "Mercury", swe.MERCURY)
    assert position.retrograde is True


def test_mercury_is_direct_between_published_windows():
    """And direct in the gaps, or the status means nothing."""
    for gap in [dt.date(2025, 5, 20), dt.date(2025, 9, 20), dt.date(2025, 12, 20)]:
        moment = dt.datetime.combine(gap, dt.time(12, 0), tzinfo=dt.timezone.utc)
        position = eph.position(eph.julian_day(moment), "Mercury", swe.MERCURY)
        assert position.retrograde is False, gap


def test_mercury_status_reports_speed_not_a_calendar():
    moment = dt.datetime(2025, 3, 25, 12, 0, tzinfo=dt.timezone.utc)
    position = eph.position(eph.julian_day(moment), "Mercury", swe.MERCURY)
    status = sky.mercury_status(moment, position)
    assert status["retrograde"] is True
    assert "Retrograde" in status["summary"]


# ---------------------------------------------------------------------------
# Nothing on the widget is invented
# ---------------------------------------------------------------------------

def test_reported_aspect_involves_a_body_that_actually_moves():
    """Outer-planet pairs sit inside a degree for years.

    Neptune sextile Pluto is real and tight, but naming it as what is happening
    *right now* would leave the line unchanged for months.
    """
    for offset in (0, 30, 90, 180, 300):
        moment = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=offset)
        snapshot = sky.snapshot(moment)
        aspect = snapshot["aspect"]
        if aspect is None:
            continue
        assert sky.MOVING_BODIES & {aspect["a"], aspect["b"]}, aspect


def test_reported_aspect_is_genuinely_within_orb():
    snapshot = sky.snapshot()
    aspect = snapshot["aspect"]
    if aspect is None:
        pytest.skip("no aspect in orb right now, which is itself valid")
    angle, orb = eph.ASPECTS[aspect["aspect"]]
    assert aspect["offset"] <= orb


def test_headline_carries_only_computed_numbers():
    """Every figure in the line must be traceable to the payload."""
    snapshot = sky.snapshot()
    headline = snapshot["headline"]

    assert snapshot["moon"]["phase"]["name"] in headline
    assert snapshot["moon"]["sign"] in headline
    assert f"{snapshot['moon']['phase']['illuminationPercent']}%" in headline

    if snapshot["aspect"]:
        assert snapshot["aspect"]["exact"] in headline
        assert snapshot["aspect"]["a"] in headline

    # No invented audience figures, ever.
    assert not re.search(r"\b\d[\d,]*\s*(people|users|readers|charts read)", headline, re.I)


def test_snapshot_has_no_social_proof_anywhere():
    """The brand's whole claim is that nothing here is made up."""
    import json

    blob = json.dumps(sky.snapshot()).lower()
    for banned in ("people are", "users", "joined", "readers", "trending",
                   "popular", "others are", "right now  "):
        assert banned not in blob, banned


def test_glyphs_are_pinned_to_text_presentation():
    """Otherwise browsers render the signs as colour emoji."""
    snapshot = sky.snapshot()
    assert snapshot["moon"]["signGlyph"].endswith(sky.TEXT)
    assert snapshot["mercury"]["glyph"].endswith(sky.TEXT)
    for body in snapshot["positions"]:
        assert body["glyph"].endswith(sky.TEXT), body["body"]


def test_every_planet_is_present_and_placed():
    snapshot = sky.snapshot()
    bodies = {p["body"] for p in snapshot["positions"]}
    assert {"Sun", "Moon", "Mercury", "Venus", "Mars",
            "Jupiter", "Saturn", "Uranus", "Neptune", "Pluto"} <= bodies
    for body in snapshot["positions"]:
        assert body["sign"] in sky.SIGN_GLYPHS
        assert "°" in body["display"]


# ---------------------------------------------------------------------------
# Caching and the endpoint
# ---------------------------------------------------------------------------

def test_snapshot_is_cached_between_calls():
    sky.reset_cache()
    first = sky.cached_snapshot()
    second = sky.cached_snapshot()
    assert first is second, "recomputing per visitor would be the app's biggest waste"
    sky.reset_cache()
    assert sky.cached_snapshot() is not first


def test_sky_endpoint_serves_the_same_payload():
    from app import app

    app.config["TESTING"] = True
    body = app.test_client().get("/api/sky").get_json()
    assert body["headline"]
    assert body["moon"]["path"].startswith("M ")
    assert isinstance(body["mercury"]["retrograde"], bool)


def test_landing_page_renders_the_live_sky():
    import html as html_module

    from app import app

    app.config["TESTING"] = True
    raw = app.test_client().get("/").get_data(as_text=True)
    # Jinja escapes the apostrophe in figures like 0°20', so compare unescaped.
    html = html_module.unescape(raw)

    snapshot = sky.cached_snapshot()
    assert snapshot["moon"]["phase"]["name"] in html
    assert snapshot["headline"] in html
    # Server-rendered, so it is in the HTML on arrival rather than popping in.
    assert 'class="sky-now"' in raw
    assert snapshot["moon"]["path"] in raw
