"""Tests for the chart, career, reading, and HTTP layers.

Astronomical accuracy is covered in ``test_ephemeris_accuracy.py``; this file
covers the product logic built on top of it. Nothing here needs network access:
the reading layer falls back to its template renderer without an API key, so the
full request path is exercised offline.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from astrology import career, places, reading  # noqa: E402
from astrology.chart import BirthData, build_chart  # noqa: E402


@pytest.fixture(scope="module")
def sample():
    """A fully specified chart with a known birth time."""
    place = places.search("New York")[0]
    birth_date, birth_time = dt.date(1997, 3, 12), dt.time(14, 25)
    moment = places.resolve_moment(birth_date, birth_time, place.timezone)
    birth = BirthData(
        name="Sam", date=birth_date, time=birth_time, time_known=True,
        place_label=place.label, latitude=place.latitude,
        longitude=place.longitude, timezone=place.timezone,
    )
    chart = build_chart(birth, moment)
    return chart, career.build_profile(chart), career.timing_summary(chart)


@pytest.fixture(scope="module")
def timeless():
    """The same birth, but with no known birth time."""
    place = places.search("New York")[0]
    birth_date = dt.date(1997, 3, 12)
    moment = places.resolve_moment(birth_date, dt.time(12, 0), place.timezone)
    birth = BirthData(
        name="Sam", date=birth_date, time=dt.time(12, 0), time_known=False,
        place_label=place.label, latitude=place.latitude,
        longitude=place.longitude, timezone=place.timezone,
    )
    chart = build_chart(birth, moment)
    return chart, career.build_profile(chart), career.timing_summary(chart)


# --------------------------------------------------------------------------
# Place resolution
# --------------------------------------------------------------------------

def test_search_ranks_the_prominent_city_first():
    assert places.search("London")[0].country == "United Kingdom"
    assert places.search("Paris")[0].country == "France"


def test_search_accepts_qualifiers():
    results = places.search("Austin, TX")
    assert results[0].admin == "Texas"


def test_search_is_accent_insensitive():
    assert places.search("Sao Paulo")[0].country == "Brazil"
    assert places.search("São Paulo")[0].country == "Brazil"


def test_search_rejects_too_short_queries():
    assert places.search("") == []
    assert places.search("a") == []


def test_historical_dst_rules_are_applied():
    """Britain ran year-round BST (UTC+1) from 1968-1971.

    Using today's rules for a 1970 birth would put the chart an hour out,
    which moves the Ascendant by about 15 degrees -- usually a whole sign.
    """
    summer = places.resolve_moment(dt.date(1970, 4, 20), dt.time(2, 30), "Europe/London")
    assert summer.utc_offset_hours == 1.0
    assert summer.dst_in_effect is False

    modern = places.resolve_moment(dt.date(2024, 1, 15), dt.time(2, 30), "Europe/London")
    assert modern.utc_offset_hours == 0.0


def test_half_hour_offsets_survive():
    india = places.resolve_moment(dt.date(1988, 2, 29), dt.time(3, 15), "Asia/Kolkata")
    assert india.utc_offset_hours == 5.5
    assert india.utc.hour == 21 and india.utc.day == 28


def test_unknown_timezone_is_rejected():
    with pytest.raises(ValueError):
        places.resolve_moment(dt.date(2000, 1, 1), dt.time(12, 0), "Mars/Olympus_Mons")


# --------------------------------------------------------------------------
# Chart structure
# --------------------------------------------------------------------------

def test_every_body_lands_in_a_house(sample):
    chart, _, _ = sample
    assert set(chart.placements) == set(chart.positions)
    assert all(1 <= h <= 12 for h in chart.placements.values())


def test_house_membership_is_consistent(sample):
    chart, _, _ = sample
    for house in range(1, 13):
        for body in chart.bodies_in_house(house):
            assert chart.house_of(body) == house


def test_element_and_modality_counts_sum_correctly(sample):
    chart, _, _ = sample
    # Ten bodies counted; the North Node is a calculated point, not a body.
    assert sum(chart.element_balance().values()) == 10
    assert sum(chart.modality_balance().values()) == 10


def test_serialized_chart_is_json_safe(sample):
    chart, _, _ = sample
    blob = json.dumps(chart.to_dict())
    assert '"positions"' in blob and '"aspects"' in blob


def test_unknown_time_uses_whole_sign_houses(timeless):
    chart, _, _ = timeless
    assert chart.houses.system == "whole_sign"


# --------------------------------------------------------------------------
# Career profile
# --------------------------------------------------------------------------

def test_profile_identifies_the_midheaven_ruler(sample):
    chart, profile, _ = sample
    from astrology.chart import RULERS

    assert profile.midheaven_ruler == RULERS[profile.midheaven_sign][0]
    assert profile.midheaven_sign == chart.sign_on_cusp(10)


def test_profile_signatures_are_weighted_and_ordered(sample):
    _, profile, _ = sample
    weights = [s.weight for s in profile.signatures]
    assert weights == sorted(weights, reverse=True)
    assert all(0 < w <= 1 for w in weights)


def test_placements_omit_houses_when_time_is_unknown(timeless):
    """The core guarantee for time-unknown charts.

    A noon-fallback house is an artefact, not a fact, so no house-derived
    *value* may survive into the profile. Field names like
    ``tenth_house_bodies`` are fine -- it is their contents that would be a
    false claim about the person.
    """
    _, profile, _ = timeless
    data = profile.to_dict()

    assert data["tenth_house_bodies"] == []
    assert data["sixth_house_bodies"] == []
    assert data["second_house_bodies"] == []
    assert data["midheaven_sign"] == ""
    assert data["midheaven_display"] == ""
    assert data["midheaven_ruler"] == ""
    assert data["midheaven_ruler_placement"] == ""

    for key in ("saturn_placement", "sun_placement", "mars_placement",
                "mercury_placement", "north_node_placement"):
        assert "house" not in data[key].lower(), key

    for signature in data["signatures"]:
        assert "house" not in signature["detail"].lower(), signature["key"]


def test_placements_include_houses_when_time_is_known(sample):
    _, profile, _ = sample
    assert "house" in profile.saturn_placement


def test_time_unknown_profile_drops_angle_signatures(timeless):
    _, profile, _ = timeless
    keys = {s.key for s in profile.signatures}
    assert "midheaven" not in keys and "tenth_house" not in keys


# --------------------------------------------------------------------------
# Timing
# --------------------------------------------------------------------------

def test_transit_windows_are_internally_consistent(sample):
    _, _, timing = sample
    assert timing["windows"], "expected at least one window in 18 months"

    for window in timing["windows"]:
        start = dt.date.fromisoformat(window["start"])
        end = dt.date.fromisoformat(window["end"])
        peak = dt.date.fromisoformat(window["peak"])
        assert start <= peak <= end
        for exact in window["exact_dates"]:
            assert start <= dt.date.fromisoformat(exact) <= end
        assert window["perfects"] == bool(window["exact_dates"])
        assert window["peak_orb"] >= 0


def test_windows_that_perfect_have_a_tiny_peak_orb(sample):
    """If an aspect goes exact, the closest sampled approach must be near zero."""
    _, _, timing = sample
    for window in timing["windows"]:
        if window["perfects"]:
            assert window["peak_orb"] < 0.6, window


def test_windows_are_ranked_by_score(sample):
    _, _, timing = sample
    scores = [w["score"] for w in timing["windows"]]
    assert scores == sorted(scores, reverse=True)


def test_time_unknown_windows_never_target_angles(timeless):
    _, _, timing = timeless
    targets = {w["natal_point"] for w in timing["windows"]}
    assert not targets & {"Midheaven", "Ascendant"}


def test_mercury_retrograde_windows_are_sane():
    windows = career.mercury_retrograde_windows(months=24)
    # Mercury retrogrades three times a year for roughly three weeks.
    assert 4 <= len(windows) <= 8
    for window in windows:
        assert 15 <= (window.end - window.start).days <= 30
    starts = [w.start for w in windows]
    assert starts == sorted(starts)


def test_saturn_returns_are_grouped_not_duplicated(sample):
    """Saturn's three retrograde passes are one return, not three.

    Reporting them separately would tell a 29-year-old they were having three
    Saturn returns inside eighteen months.
    """
    chart, _, timing = sample
    saturn = [c for c in timing["cycles"] if c["name"].startswith("Saturn return")]
    assert len(saturn) == 3  # over a ~90 year span

    for earlier, later in zip(saturn, saturn[1:]):
        gap_days = (
            dt.date.fromisoformat(later["start"]) - dt.date.fromisoformat(earlier["start"])
        ).days
        assert 27 * 365 < gap_days < 32 * 365, "returns should be ~29.5 years apart"


def test_first_saturn_return_lands_near_age_twenty_nine(sample):
    chart, _, timing = sample
    first = next(c for c in timing["cycles"] if c["name"] == "Saturn return #1")
    peak = dt.date.fromisoformat(first["start"]) + dt.timedelta(days=180)
    age = (peak - chart.moment.utc.date()).days / 365.25
    assert 28 <= age <= 31, f"first Saturn return at age {age:.1f}"


def test_cycle_status_matches_the_dates(sample):
    _, _, timing = sample
    today = dt.date.today()
    for cycle in timing["cycles"]:
        start = dt.date.fromisoformat(cycle["start"])
        end = dt.date.fromisoformat(cycle["end"])
        expected = "past" if end < today else "upcoming" if start > today else "current"
        assert cycle["status"] == expected


# --------------------------------------------------------------------------
# Reading layer
# --------------------------------------------------------------------------

def test_free_tier_gets_strictly_less_data_than_paid(sample):
    """The paywall is enforced in the data, not in the prompt.

    A tier boundary that exists only as an instruction is one jailbreak away
    from leaking; this way the free tier physically cannot see paid content.
    """
    chart, profile, timing = sample
    free = reading.build_facts(chart, profile, timing, "free")
    paid = reading.build_facts(chart, profile, timing, "paid")
    assert len(free["transitWindows"]) < len(paid["transitWindows"])
    assert len(free["transitWindows"]) == 1


def test_facts_hide_angles_when_time_is_unknown(timeless):
    chart, profile, timing = timeless
    facts = reading.build_facts(chart, profile, timing, "paid")
    assert "angles" not in facts
    assert "UNKNOWN" in facts["note"]
    assert not any("house" in p for p in facts["placements"])


def test_offline_reading_matches_the_response_schema(sample):
    chart, profile, timing = sample
    for tier in ("free", "paid"):
        result = reading.generate(chart, profile, timing, tier)
        content = result.content
        assert set(reading.READING_SCHEMA["required"]) <= set(content)
        assert content["headline"] and content["core_read"]
        assert len(content["strengths"]) >= 2
        assert content["friction"] and content["timing"]
        for item in content["strengths"] + content["friction"]:
            assert item["evidence"], "every claim must cite a placement"


def test_offline_reading_is_labelled_as_such(sample):
    chart, profile, timing = sample
    result = reading.generate(chart, profile, timing, "free")
    if not reading.api_configured():
        assert result.source == "offline"
        assert result.model is None


def test_offline_reading_cites_real_computed_positions(sample):
    """Evidence strings must contain actual chart values, not invented ones."""
    chart, profile, timing = sample
    content = reading.offline_reading(chart, profile, timing, "paid")
    valid = {p.display for p in chart.positions.values()}
    for item in content["strengths"] + content["friction"]:
        assert any(v in item["evidence"] for v in valid), item["evidence"]


def test_offline_reading_omits_houses_without_a_birth_time(timeless):
    chart, profile, timing = timeless
    content = reading.offline_reading(chart, profile, timing, "paid")
    for item in content["strengths"] + content["friction"]:
        assert "house" not in item["evidence"].lower()


def test_paid_reading_has_more_timing_entries(sample):
    chart, profile, timing = sample
    free = reading.offline_reading(chart, profile, timing, "free")
    paid = reading.offline_reading(chart, profile, timing, "paid")
    assert len(paid["timing"]) >= len(free["timing"])
    assert len(paid["strengths"]) > len(free["strengths"])


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from app import app

    app.config["TESTING"] = True
    return app.test_client()


PAYLOAD = {
    "name": "Sam",
    "date": "1997-03-12",
    "time": "14:25",
    "timeKnown": True,
    "place": "New York City, New York, United States",
    "latitude": 40.7143,
    "longitude": -74.006,
    "timezone": "America/New_York",
}


def test_index_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.data.lower()

    # The wordmark, the title and the footer all carry the product name, so a
    # rename that misses any of them fails here rather than in a screenshot.
    assert body.count(b"northstar") >= 3
    assert b"<title>northstar" in body

    # "transit" survives only as the astrology term, never as the product name.
    assert b">transit<" not in body, "the wordmark still says the old name"


def test_health_and_config(client):
    for path in ("/health", "/api/config"):
        assert client.get(path).status_code == 200


def test_place_search_endpoint(client):
    body = client.get("/api/places?q=Tokyo").get_json()
    assert body["results"][0]["timezone"] == "Asia/Tokyo"


def test_place_search_handles_junk(client):
    assert client.get("/api/places?q=").get_json()["results"] == []
    assert client.get("/api/places?q=zzzzqqqqxxxx").get_json()["results"] == []


def test_chart_endpoint_returns_a_full_chart(client):
    body = client.post("/api/chart", json=PAYLOAD).get_json()
    assert len(body["chart"]["positions"]) == 11
    assert len(body["chart"]["houses"]) == 12
    assert body["chart"]["angles"]["midheaven"]["display"]
    assert body["timing"]["windows"]


def test_reading_tier_is_decided_by_the_server(client):
    """The client used to pick its own tier. It no longer can.

    Paid access now requires a membership recorded by a signed Whop webhook;
    full coverage of that path lives in test_entitlements.py.
    """
    for requested in ("free", "paid", "enterprise", None):
        payload = dict(PAYLOAD)
        if requested is not None:
            payload["tier"] = requested
        body = client.post("/api/reading", json=payload).get_json()
        assert body["tier"] == "free", f"tier={requested!r} must not grant paid access"
        assert body["entitlement"]["entitled"] is False


@pytest.mark.parametrize(
    "payload,fragment",
    [
        ({}, "birth date"),
        ({**PAYLOAD, "date": "12/03/1997"}, "YYYY-MM-DD"),
        ({**PAYLOAD, "date": "1850-01-01"}, "between 1900"),
        ({**PAYLOAD, "date": "2999-01-01"}, "between 1900"),
        ({**PAYLOAD, "time": "25:99"}, "HH:MM"),
        ({**PAYLOAD, "latitude": 999}, "out of range"),
        ({**PAYLOAD, "latitude": "abc"}, "must be numbers"),
        # No coordinates and an unresolvable name: the server still answers 400,
        # but the message now names the city the user typed instead of telling
        # them to "pick from the list" when no list may have appeared.
        ({**PAYLOAD, "latitude": None, "longitude": None, "place": "Zzzqqq"}, "couldn't find a city"),
    ],
)
def test_invalid_input_is_rejected_with_400(client, payload, fragment):
    response = client.post("/api/chart", json=payload)
    assert response.status_code == 400
    assert fragment in response.get_json()["error"]


def test_time_unknown_response_omits_angle_claims(client):
    """No angle may be asserted as a fact without a birth time.

    Saying "a birth time would let us place your Midheaven" is honest and
    useful, so the word itself is not banned -- what is banned is stating a
    *position* for an angle, or citing one as evidence.
    """
    body = client.post(
        "/api/reading", json={**PAYLOAD, "timeKnown": False}
    ).get_json()
    content = body["content"]

    for item in content["strengths"] + content["friction"] + content["timing"]:
        evidence = item["evidence"].lower()
        assert "midheaven" not in evidence
        assert "ascendant" not in evidence
        assert "house" not in evidence

    # No "<degrees> <sign>" position may be attributed to an angle anywhere.
    blob = json.dumps(content).lower()
    for angle in ("midheaven", "ascendant"):
        for match in re.finditer(angle, blob):
            window = blob[match.start(): match.start() + 90]
            assert "°" not in window, f"angle position asserted: {window}"


def test_question_requires_a_question(client):
    assert client.post("/api/question", json=PAYLOAD).status_code == 400
    long_question = {**PAYLOAD, "question": "x" * 501}
    assert client.post("/api/question", json=long_question).status_code == 400


def test_question_endpoint_is_paid_only(client):
    """Asking about a decision is a paid feature, so it needs a membership.

    The streaming behaviour itself is covered in test_entitlements.py, where a
    session can be given one.
    """
    response = client.post("/api/question", json={**PAYLOAD, "question": "Should I quit?"})
    assert response.status_code == 402


def test_repeated_requests_are_cached(client):
    """Second identical request must not recompute the chart."""
    from app import _chart_cache

    _chart_cache.clear()
    client.post("/api/chart", json=PAYLOAD)
    assert len(_chart_cache) == 1
    client.post("/api/chart", json=PAYLOAD)
    assert len(_chart_cache) == 1


# ---------------------------------------------------------------------------
# Birth-place picker
# ---------------------------------------------------------------------------


def test_place_search_backs_the_picker(client):
    """The picker is offline: no third-party API, no key, no CORS surface."""
    for query, expected in [
        ("Dublin", "Dublin, Ireland"),
        ("new york", "New York City"),
        ("Sao Paulo", "São Paulo"),       # accents optional
        ("München", "Munich"),            # local spelling resolves
        ("NYC", "New York City"),          # common alias
    ]:
        response = client.get(f"/api/places?q={query}")
        assert response.status_code == 200
        results = response.get_json()["results"]
        assert results, f"no results for {query!r}"
        assert expected in results[0]["label"], f"{query!r} -> {results[0]['label']}"

        # Every result must carry what the chart engine needs.
        for place in results:
            assert place["timezone"]
            assert -90 <= place["latitude"] <= 90
            assert -180 <= place["longitude"] <= 180


def test_place_dropdown_can_open_upward():
    """Guards the fix for the picker opening below the fold.

    The list is absolutely positioned under the input, which sits low in the
    form; on a 1280x800 laptop it opened past the bottom of the window where it
    could not be clicked. positionSuggestions() measures the space and flips the
    list above the field when there isn't room. Full end-to-end coverage lives
    in scripts/verify_place_picker.js, which needs a browser; this asserts the
    two halves of the mechanism are still wired together.
    """
    here = os.path.dirname(__file__)
    script = open(os.path.join(here, "..", "static", "app.js")).read()
    styles = open(os.path.join(here, "..", "static", "styles.css")).read()

    assert "function positionSuggestions" in script
    assert "positionSuggestions();" in script, "never called after opening"
    assert "flip-up" in script, "no upward fallback"
    assert ".suggestions.flip-up" in styles, "flip-up has no styling"
    assert "bottom: calc(100% + 6px)" in styles


def test_typed_place_resolves_without_coordinates(client):
    """The picker must be a convenience, not a requirement.

    If the dropdown fails for any reason -- offline, blocked, a stale build --
    the user can still type a city and get a chart, because the server holds the
    same index the dropdown reads from.
    """
    payload = {
        "name": "Typed",
        "date": "1993-08-04",
        "time": "07:15",
        "timeKnown": True,
        "place": "Lisbon",       # no latitude, longitude or timezone
    }
    response = client.post("/api/chart", json=payload)
    assert response.status_code == 200

    chart = response.get_json()["chart"]
    assert "Lisbon" in chart["birth"]["place"]
    assert chart["birth"]["timezone"] == "Europe/Lisbon"


def test_typed_place_produces_the_same_chart_as_a_picked_one(client):
    """Typing and picking must not silently give different answers."""
    base = {"name": "Same", "date": "1993-08-04", "time": "07:15", "timeKnown": True}
    picked = places.search("Lisbon", 1)[0]

    typed = client.post("/api/chart", json={**base, "place": "Lisbon"}).get_json()
    chosen = client.post("/api/chart", json={
        **base, "place": picked.label, "latitude": picked.latitude,
        "longitude": picked.longitude, "timezone": picked.timezone,
    }).get_json()

    assert typed["chart"]["angles"] == chosen["chart"]["angles"]
    assert typed["chart"]["positions"] == chosen["chart"]["positions"]


def test_partial_typing_ranks_the_obvious_city_first():
    """Prefix search must not be ranked on population alone.

    Quito's alternate name is "San Francisco de Quito" and Quito is the bigger
    city, so ranking prefix matches by size alone made "San Fr" return Quito.
    A place whose own name matches has to win.
    """
    assert places.search("San Fr", 3)[0].name == "San Francisco"
    assert places.search("San Fran", 3)[0].name == "San Francisco"
    assert places.search("New Yor", 3)[0].name.startswith("New York")
    assert places.search("Los Ang", 3)[0].admin == "California"
    assert places.search("Sao Pau", 3)[0].country == "Brazil"
    assert places.search("Cambridg", 3)[0].country == "United Kingdom"


def test_exact_name_still_beats_a_bigger_alias_match():
    results = places.search("San Francisco", 5)
    assert results[0].name == "San Francisco"
    assert results[0].admin == "California"


def test_the_boot_check_warns_when_checkout_is_live_on_undeclared_storage(monkeypatch, caplog):
    """Taking cards onto storage nobody has vouched for must not be silent.

    From inside the container an ephemeral directory is indistinguishable from
    a mounted disk, so this cannot be detected -- only declared. The warning is
    the only thing standing between a launch and every customer quietly losing
    access at the next deploy.
    """
    import app as app_module

    monkeypatch.setattr(app_module, "whop_config", lambda: {"configured": True})
    monkeypatch.delenv("ASTRO_STORAGE_DURABLE", raising=False)

    with caplog.at_level(logging.WARNING):
        app_module._check_payment_readiness()
    assert "CHECKOUT IS LIVE" in caplog.text


def test_the_boot_check_is_quiet_once_durability_is_declared(monkeypatch, caplog):
    import app as app_module

    monkeypatch.setattr(app_module, "whop_config", lambda: {"configured": True})
    monkeypatch.setenv("ASTRO_STORAGE_DURABLE", "1")

    with caplog.at_level(logging.WARNING):
        app_module._check_payment_readiness()
    assert "CHECKOUT IS LIVE" not in caplog.text


def test_the_boot_check_is_quiet_while_checkout_is_off(monkeypatch, caplog):
    """No checkout, no money, nothing to lose."""
    import app as app_module

    monkeypatch.setattr(app_module, "whop_config", lambda: {"configured": False})
    monkeypatch.delenv("ASTRO_STORAGE_DURABLE", raising=False)

    with caplog.at_level(logging.WARNING):
        app_module._check_payment_readiness()
    assert "CHECKOUT IS LIVE" not in caplog.text
