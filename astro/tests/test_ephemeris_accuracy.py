"""Accuracy tests for the chart engine.

The PRD calls the astronomical layer the highest-risk component and asks for it
to be verified before any interpretation is built on top. These tests check the
engine against *external* references -- published eclipse times, published
equinox times, known retrograde periods, and an independent re-derivation of
the angles from spherical trigonometry -- rather than against its own output.

Run: python -m pytest astro/tests/ -v
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sys

import pytest
import swisseph as swe

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from astrology import ephemeris as eph  # noqa: E402


def utc(*args) -> dt.datetime:
    return dt.datetime(*args, tzinfo=dt.timezone.utc)


ARCMIN = 1.0 / 60.0


# --------------------------------------------------------------------------
# 1. Solar eclipses: an independent, precisely published check on Sun+Moon.
#
# At greatest eclipse the Sun and Moon are at (very nearly) the same ecliptic
# longitude. Times below are the published greatest-eclipse instants from
# NASA's eclipse catalogue. If our Sun or Moon were wrong by even a few
# arcminutes, the computed separation at these instants would not be tiny.
# --------------------------------------------------------------------------

ECLIPSES = [
    # (greatest eclipse UT, description)
    (utc(2024, 4, 8, 18, 17, 16), "2024-04-08 total (North America)"),
    (utc(2017, 8, 21, 18, 26, 40), "2017-08-21 total (United States)"),
    (utc(1999, 8, 11, 11, 3, 4), "1999-08-11 total (Europe)"),
    (utc(2026, 8, 12, 17, 46, 1), "2026-08-12 total (Spain/Iceland)"),
]


@pytest.mark.parametrize("moment,label", ECLIPSES)
def test_sun_moon_conjunct_at_published_eclipse(moment, label):
    """Sun and Moon must be sensibly conjunct at each published eclipse."""
    jd = eph.julian_day(moment)
    sun = eph.position(jd, "Sun", swe.SUN)
    moon = eph.position(jd, "Moon", swe.MOON)
    separation = eph.angular_separation(sun.longitude, moon.longitude)

    # The Moon moves ~0.55°/hour, so even a several-minute timing difference
    # between "greatest eclipse" (a geometric, observer-dependent instant) and
    # exact ecliptic conjunction keeps this well under a third of a degree.
    assert separation < 0.3, f"{label}: Sun-Moon separation {separation:.4f}°"


def test_eclipse_longitude_matches_published_zodiacal_position():
    """The 2024-04-08 eclipse is published at 19°24' Aries."""
    jd = eph.julian_day(utc(2024, 4, 8, 18, 17, 16))
    sun = eph.position(jd, "Sun", swe.SUN)
    assert sun.sign == "Aries"
    assert sun.degree_in_sign == pytest.approx(19.4, abs=0.05)


def test_eclipse_search_reproduces_published_times():
    """Swiss Ephemeris' own eclipse search must land on the published instants.

    This exercises a completely different code path (iterative geometric
    search) than calc_ut, so agreement with the published catalogue is
    meaningful corroboration rather than a tautology.
    """
    for moment, label in ECLIPSES:
        start = eph.julian_day(moment - dt.timedelta(days=5))
        _ret, times = swe.sol_eclipse_when_glob(start, eph.CALC_FLAGS, 0, False)
        found = eph.jd_to_datetime(times[0])
        drift = abs((found - moment).total_seconds())
        assert drift < 120, f"{label}: found {found}, expected {moment} ({drift:.0f}s off)"


# --------------------------------------------------------------------------
# 2. Equinoxes and solstices: published to the minute, and they pin the zero
#    point of the tropical zodiac -- the frame every longitude here is measured
#    against. If the reference frame were off, every sign placement would be.
# --------------------------------------------------------------------------

CARDINAL_INGRESSES = [
    (utc(2024, 3, 20, 3, 6), 0.0, "March equinox 2024"),
    (utc(2024, 6, 20, 20, 51), 90.0, "June solstice 2024"),
    (utc(2024, 9, 22, 12, 44), 180.0, "September equinox 2024"),
    (utc(2024, 12, 21, 9, 21), 270.0, "December solstice 2024"),
    (utc(2000, 3, 20, 7, 35), 0.0, "March equinox 2000"),
    (utc(2025, 3, 20, 9, 1), 0.0, "March equinox 2025"),
]


@pytest.mark.parametrize("moment,expected_longitude,label", CARDINAL_INGRESSES)
def test_sun_at_cardinal_point(moment, expected_longitude, label):
    """The Sun sits on the cardinal point at each published ingress time."""
    jd = eph.julian_day(moment)
    sun = eph.position(jd, "Sun", swe.SUN)
    offset = eph.angular_separation(sun.longitude, expected_longitude)

    # Published times are given to the minute; the Sun moves ~2.5'/minute, so
    # rounding alone permits a couple of arcminutes.
    assert offset < 3 * ARCMIN, f"{label}: Sun off by {offset * 60:.2f} arcmin"


# --------------------------------------------------------------------------
# 3. Retrograde detection. Career readings lean on this hard ("don't sign
#    while Mercury is retrograde"), so a sign error here would be visible to
#    every user. Periods below are the published 2024 stations.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "moment,expected_retrograde",
    [
        (utc(2024, 4, 10, 12, 0), True),    # inside Apr 1 - Apr 25 retrograde
        (utc(2024, 5, 10, 12, 0), False),   # after it stations direct
        (utc(2024, 8, 15, 12, 0), True),    # inside Aug 5 - Aug 28 retrograde
        (utc(2024, 12, 5, 12, 0), True),    # inside Nov 26 - Dec 15 retrograde
        (utc(2024, 1, 15, 12, 0), False),   # direct between retrogrades
    ],
)
def test_mercury_retrograde_periods(moment, expected_retrograde):
    jd = eph.julian_day(moment)
    mercury = eph.position(jd, "Mercury", swe.MERCURY)
    assert mercury.retrograde is expected_retrograde


def test_station_search_finds_published_station():
    """Mercury stations direct on 2024-04-25; the search must find it."""
    jd = eph.julian_day(utc(2024, 4, 10))
    result = eph.next_station(jd, "Mercury", swe.MERCURY)
    assert result is not None
    station_jd, direction = result
    assert direction == "direct"
    found = eph.jd_to_datetime(station_jd)
    assert abs((found - utc(2024, 4, 25, 12, 0)).total_seconds()) < 86400


def test_outer_planets_are_retrograde_roughly_five_months_a_year():
    """Sanity bound on speed signs across a full year.

    Saturn is retrograde ~4.5 months per year. A bug in speed handling would
    push this far outside the band.
    """
    start = eph.julian_day(utc(2024, 1, 1))
    retrograde_days = sum(
        1 for d in range(365)
        if eph.position(start + d, "Saturn", swe.SATURN).retrograde
    )
    assert 120 <= retrograde_days <= 150, f"Saturn retrograde {retrograde_days} days"


# --------------------------------------------------------------------------
# 4. Angles and houses, re-derived independently.
#
# The Ascendant and Midheaven are computed here from spherical trigonometry
# using only sidereal time and obliquity, and compared against what the
# Swiss Ephemeris house routine returns. Two independent derivations agreeing
# to arcseconds means the angles -- and therefore the 10th house, the career
# house the whole product rests on -- are right.
# --------------------------------------------------------------------------

CHART_CASES = [
    (utc(1995, 7, 14, 16, 30), 40.7128, -74.0060, "New York"),
    (utc(1988, 2, 29, 3, 15), 51.5074, -0.1278, "London"),
    (utc(2001, 11, 5, 23, 45), -33.8688, 151.2093, "Sydney"),
    (utc(1979, 9, 21, 9, 5), 35.6762, 139.6503, "Tokyo"),
    (utc(2003, 12, 25, 12, 0), -23.5505, -46.6333, "Sao Paulo"),
]


def _independent_angles(jd: float, latitude: float, longitude: float):
    """Ascendant and MC from first principles (Meeus, Astronomical Algorithms)."""
    ramc = math.radians((eph.sidereal_time_deg(jd) + longitude) % 360.0)
    eps = math.radians(eph.obliquity(jd))
    phi = math.radians(latitude)

    mc = math.degrees(math.atan2(math.sin(ramc), math.cos(ramc) * math.cos(eps))) % 360.0
    asc = math.degrees(
        math.atan2(
            math.cos(ramc),
            -(math.sin(ramc) * math.cos(eps) + math.tan(phi) * math.sin(eps)),
        )
    ) % 360.0
    return asc, mc


@pytest.mark.parametrize("moment,lat,lon,label", CHART_CASES)
def test_angles_match_independent_derivation(moment, lat, lon, label):
    jd = eph.julian_day(moment)
    h = eph.houses(jd, lat, lon)
    asc_expected, mc_expected = _independent_angles(jd, lat, lon)

    assert eph.angular_separation(h.ascendant, asc_expected) < ARCMIN, (
        f"{label}: Ascendant {h.ascendant:.5f} vs {asc_expected:.5f}"
    )
    assert eph.angular_separation(h.midheaven, mc_expected) < ARCMIN, (
        f"{label}: MC {h.midheaven:.5f} vs {mc_expected:.5f}"
    )


@pytest.mark.parametrize("moment,lat,lon,label", CHART_CASES)
def test_house_ring_is_well_formed(moment, lat, lon, label):
    """Cusps must go strictly forward around the circle and close on 360°."""
    jd = eph.julian_day(moment)
    h = eph.houses(jd, lat, lon)

    assert len(h.cusps) == 12
    assert h.cusp(1) == pytest.approx(h.ascendant, abs=1e-6), f"{label}: 1st cusp != Asc"
    assert h.cusp(10) == pytest.approx(h.midheaven, abs=1e-6), f"{label}: 10th cusp != MC"

    spans = [
        (h.cusps[(i + 1) % 12] - h.cusps[i]) % 360.0
        for i in range(12)
    ]
    assert all(s > 0 for s in spans), f"{label}: non-advancing cusp"
    assert sum(spans) == pytest.approx(360.0, abs=1e-6), f"{label}: ring does not close"

    # Opposite cusps are exactly 180° apart in every quadrant-based system.
    for i in range(6):
        opposite = eph.angular_separation(h.cusps[i], h.cusps[i + 6])
        assert opposite == pytest.approx(180.0, abs=1e-6), f"{label}: cusp {i+1} axis"


@pytest.mark.parametrize("moment,lat,lon,label", CHART_CASES)
def test_house_lookup_agrees_with_cusp_ring(moment, lat, lon, label):
    """Every cusp longitude must resolve to its own house, including the wrap."""
    jd = eph.julian_day(moment)
    h = eph.houses(jd, lat, lon)
    for house in range(1, 13):
        probe = h.cusp(house) + 0.001  # just inside the cusp
        assert h.house_of(probe) == house, f"{label}: house {house} lookup"


def test_placidus_falls_back_above_the_polar_circle():
    """Placidus is undefined near the poles; we must degrade, not emit noise."""
    jd = eph.julian_day(utc(1990, 1, 1, 12, 0))
    h = eph.houses(jd, 78.2, 15.6)  # Svalbard
    assert h.system == "whole_sign"
    assert len(h.cusps) == 12


# --------------------------------------------------------------------------
# 5. Cross-checks on the rest of the pipeline.
# --------------------------------------------------------------------------

def test_julian_day_round_trip():
    moment = utc(1993, 6, 17, 14, 23, 45)
    assert abs((eph.jd_to_datetime(eph.julian_day(moment)) - moment).total_seconds()) < 1


def test_julian_day_requires_timezone_aware_input():
    with pytest.raises(ValueError):
        eph.julian_day(dt.datetime(1990, 1, 1, 12, 0))


def test_inner_planets_stay_near_the_sun():
    """Mercury never exceeds ~28° elongation, Venus ~47°. A frame or unit bug
    would break this immediately."""
    start = eph.julian_day(utc(2024, 1, 1))
    for d in range(0, 365, 7):
        jd = start + d
        sun = eph.position(jd, "Sun", swe.SUN).longitude
        mercury = eph.position(jd, "Mercury", swe.MERCURY).longitude
        venus = eph.position(jd, "Venus", swe.VENUS).longitude
        assert eph.angular_separation(sun, mercury) < 29.0
        assert eph.angular_separation(sun, venus) < 48.0


def test_planet_speeds_are_in_expected_bands():
    jd = eph.julian_day(utc(2024, 6, 1))
    positions = eph.all_positions(jd)
    assert 11.0 < abs(positions["Moon"].speed) < 16.0     # ~13°/day
    assert 0.9 < abs(positions["Sun"].speed) < 1.05       # ~1°/day
    assert abs(positions["Pluto"].speed) < 0.05           # very slow


def test_sign_boundaries():
    assert eph.sign_of(0.0) == ("Aries", 0.0)
    assert eph.sign_of(29.999)[0] == "Aries"
    assert eph.sign_of(30.0) == ("Taurus", 0.0)
    assert eph.sign_of(359.9)[0] == "Pisces"
    assert eph.sign_of(360.0) == ("Aries", 0.0)
    assert eph.sign_of(-1.0)[0] == "Pisces"


def test_position_display_formatting():
    jd = eph.julian_day(utc(2024, 4, 8, 18, 17, 16))
    sun = eph.position(jd, "Sun", swe.SUN)
    assert "Aries" in sun.display
    assert "°" in sun.display and "'" in sun.display


def test_aspect_detection_is_symmetric_and_bounded():
    jd = eph.julian_day(utc(1995, 7, 14, 16, 30))
    positions = eph.all_positions(jd)
    aspects = eph.find_aspects(positions)

    for aspect in aspects:
        assert aspect.body_a != aspect.body_b
        assert aspect.orb <= 8.0
        actual = eph.angular_separation(
            positions[aspect.body_a].longitude,
            positions[aspect.body_b].longitude,
        )
        assert abs(actual - aspect.exact_angle) == pytest.approx(aspect.orb, abs=1e-9)

    # Each pair may hold at most one aspect.
    pairs = [frozenset((a.body_a, a.body_b)) for a in aspects]
    assert len(pairs) == len(set(pairs))


def test_applying_aspect_logic_matches_forward_motion():
    """An applying aspect must have a smaller orb shortly afterwards."""
    jd = eph.julian_day(utc(2024, 3, 1))
    positions = eph.all_positions(jd)
    later = eph.all_positions(jd + 0.02)
    for aspect in eph.find_aspects(positions):
        orb_now = abs(
            eph.angular_separation(
                positions[aspect.body_a].longitude, positions[aspect.body_b].longitude
            ) - aspect.exact_angle
        )
        orb_later = abs(
            eph.angular_separation(
                later[aspect.body_a].longitude, later[aspect.body_b].longitude
            ) - aspect.exact_angle
        )
        assert aspect.applying == (orb_later < orb_now), (
            f"{aspect.body_a}-{aspect.body_b} {aspect.aspect}"
        )


def test_solar_return_lands_on_the_natal_sun():
    natal_jd = eph.julian_day(utc(1995, 7, 14, 16, 30))
    natal_sun = eph.position(natal_jd, "Sun", swe.SUN).longitude
    for year in (2024, 2025, 2026):
        return_jd = eph.solar_return_jd(natal_jd, natal_sun, year)
        returned = eph.position(return_jd, "Sun", swe.SUN).longitude
        assert eph.angular_separation(returned, natal_sun) < 0.001
        moment = eph.jd_to_datetime(return_jd)
        assert moment.year == year
        assert moment.month == 7  # solar return always falls near the birthday


def test_historical_dates_remain_computable():
    """Users born in the 1940s must not hit an ephemeris range error."""
    for year in (1940, 1955, 1970, 2010, 2025):
        jd = eph.julian_day(utc(year, 6, 15, 12, 0))
        positions = eph.all_positions(jd)
        assert len(positions) == len(eph.PLANETS)
        assert all(0 <= p.longitude < 360 for p in positions.values())
