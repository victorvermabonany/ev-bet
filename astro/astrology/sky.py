"""Today's sky, computed live.

Everything on the landing page that claims to be current is produced here from
the same Swiss Ephemeris the charts use. Nothing is hardcoded, scheduled, or
approximated from a lookup table: the Moon's phase comes from the real
Sun-Moon elongation at this moment, and the retrograde status comes from
Mercury's actual instantaneous speed.

That matters beyond correctness. The whole product is positioned on "real data,
not vibes", so a marketing widget showing a plausible-looking but invented sky
would undercut the one claim the brand rests on. If this module cannot compute
something it says so rather than guessing.
"""

from __future__ import annotations

import datetime as dt
import math
import threading

from . import ephemeris as eph

# U+FE0E, the text variation selector. Several of these code points have an
# emoji presentation by default, so a browser renders ♌ or ♀ as a colour emoji
# that fights the typography around it. This pins them to the text glyph.
TEXT = "\ufe0e"


def _text(glyph: str) -> str:
    return glyph + TEXT if glyph else glyph


# Traditional glyphs. Used in the UI as typography rather than decoration, so
# they live next to the data they label rather than being hardcoded in HTML.
GLYPHS = {
    "Sun": "☉", "Moon": "☽", "Mercury": "☿", "Venus": "♀", "Mars": "♂",
    "Jupiter": "♃", "Saturn": "♄", "Uranus": "♅", "Neptune": "♆",
    "Pluto": "♇", "North Node": "☊",
}

SIGN_GLYPHS = {
    "Aries": "♈", "Taurus": "♉", "Gemini": "♊", "Cancer": "♋",
    "Leo": "♌", "Virgo": "♍", "Libra": "♎", "Scorpio": "♏",
    "Sagittarius": "♐", "Capricorn": "♑", "Aquarius": "♒", "Pisces": "♓",
}

ASPECT_GLYPHS = {
    "conjunction": "☌", "opposition": "☍", "trine": "△",
    "square": "□", "sextile": "⚹",
}

# What each aspect actually means for work, in one clause. Plain description of
# the geometry's traditional reading -- not a prediction about the visitor.
ASPECT_SENSE = {
    "conjunction": "the two acting as one",
    "opposition": "a pull in two directions at once",
    "trine": "an easy, unforced channel between them",
    "square": "friction that tends to force a decision",
    "sextile": "an opening that rewards being taken up",
}

# Bodies whose mutual aspects are worth naming on a landing page. The Moon is
# excluded on purpose: it changes aspect every few hours, so it would make the
# line churn without saying anything durable about the day.
HEADLINE_BODIES = ("Sun", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
                   "Uranus", "Neptune", "Pluto")

# At least one body in a reported aspect must come from this set. Without it the
# tightest aspect is almost always between two outer planets -- Neptune sextile
# Pluto sits inside a degree for years at a time. That is real, but presenting
# it as what is happening *right now* would be misleading: the line would not
# change for months. These move enough that naming them is a statement about
# today.
MOVING_BODIES = frozenset({"Sun", "Mercury", "Venus", "Mars", "Jupiter"})

# Eight conventional lunar phases, by Sun-Moon elongation in degrees.
PHASES = (
    (11.25, "New Moon"),
    (78.75, "Waxing crescent"),
    (101.25, "First quarter"),
    (168.75, "Waxing gibbous"),
    (191.25, "Full Moon"),
    (258.75, "Waning gibbous"),
    (281.25, "Last quarter"),
    (348.75, "Waning crescent"),
    (360.01, "New Moon"),
)

CACHE_SECONDS = 600  # the Moon moves ~0.5°/hour; ten minutes is still "now"

_lock = threading.Lock()
_cache: tuple[dt.datetime, dict] | None = None


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _dms(degrees: float) -> str:
    """Format a separation the way an ephemeris would: 2°14'."""
    whole = int(degrees)
    minutes = int(round((degrees - whole) * 60))
    if minutes == 60:
        whole, minutes = whole + 1, 0
    return f"{whole}°{minutes:02d}'"


def moon_phase(sun_longitude: float, moon_longitude: float) -> dict:
    """The Moon's phase from the real Sun-Moon elongation.

    Illumination is the standard ``(1 - cos e) / 2``, which is the fraction of
    the disc lit as seen from Earth. Waxing is simply an elongation under 180
    degrees -- the Moon pulling ahead of the Sun.
    """
    elongation = (moon_longitude - sun_longitude) % 360.0
    illumination = (1.0 - math.cos(math.radians(elongation))) / 2.0

    name = "New Moon"
    for limit, label in PHASES:
        if elongation < limit:
            name = label
            break

    return {
        "name": name,
        "elongation": round(elongation, 2) % 360.0,
        "illumination": round(illumination, 4),
        "illuminationPercent": int(round(illumination * 100)),
        "waxing": elongation < 180.0,
    }


def moon_path(illumination: float, waxing: bool, radius: float = 12.0) -> str:
    """An SVG path for the lit portion of the disc, drawn from real numbers.

    The terminator is the projection of a circle onto the disc, so it is an
    ellipse whose semi-minor axis is ``r * |1 - 2k|``. Rendering it this way
    means the graphic is the illumination figure -- there is no sprite sheet of
    eight phases pretending to be today.

    Sweep flags: an arc from the top of the disc to the bottom passes through
    +x with sweep=1 and -x with sweep=0 (SVG's y axis points down).
    """
    k = min(max(illumination, 0.0), 1.0)
    cx = cy = radius
    rx = radius * abs(1.0 - 2.0 * k)

    # The sweep flag is relative to the direction of travel, and the inner arc
    # runs bottom-to-top -- the reverse of the outer one -- so equal flags put
    # the two arcs on opposite sides of the disc. Getting this backwards
    # renders a new moon as a full disc and a full moon as nothing at all.
    if waxing:
        outer, inner = 1, (0 if k < 0.5 else 1)
    else:
        outer, inner = 0, (1 if k < 0.5 else 0)

    return (
        f"M {cx} {cy - radius} "
        f"A {radius} {radius} 0 0 {outer} {cx} {cy + radius} "
        f"A {rx:.3f} {radius} 0 0 {inner} {cx} {cy - radius} Z"
    )


def mercury_status(moment: dt.datetime, position: eph.Position) -> dict:
    """Whether Mercury is retrograde right now, and the dates either side.

    Read from Mercury's instantaneous speed rather than a calendar, then the
    surrounding period is located by scanning for the station.
    """
    from .career import mercury_retrograde_windows

    today = moment.date()
    windows = mercury_retrograde_windows(start=today, months=14)

    current = next((w for w in windows if w.start <= today <= w.end), None)
    upcoming = next((w for w in windows if w.start > today), None)

    status = {
        "retrograde": position.retrograde,
        "sign": position.sign,
        "signGlyph": _text(SIGN_GLYPHS.get(position.sign, "")),
        "display": position.display,
        "glyph": _text(GLYPHS["Mercury"]),
    }

    if position.retrograde and current:
        status["until"] = current.end.isoformat()
        status["untilPretty"] = _pretty(current.end)
        status["since"] = current.start.isoformat()
        status["summary"] = f"Retrograde in {position.sign} until {_pretty(current.end)}"
    elif position.retrograde:
        # Speed says retrograde but the scan found no enclosing window; report
        # the speed, which is the primary source, and skip the dates.
        status["summary"] = f"Retrograde in {position.sign}"
    elif upcoming:
        status["next"] = upcoming.start.isoformat()
        status["nextPretty"] = _pretty(upcoming.start)
        status["nextEnd"] = upcoming.end.isoformat()
        status["summary"] = f"Direct in {position.sign} · next retrograde {_pretty(upcoming.start)}"
    else:
        status["summary"] = f"Direct in {position.sign}"

    return status


def _pretty(day: dt.date) -> str:
    return f"{day.day} {day.strftime('%b')}"


def tightest_aspect(positions: dict[str, eph.Position]) -> dict | None:
    """The closest aspect currently held between two slow-moving bodies.

    Returns None rather than inventing something when nothing is in orb, which
    happens and is itself worth saying.
    """
    best = None
    names = [n for n in HEADLINE_BODIES if n in positions]

    for i, first in enumerate(names):
        for second in names[i + 1:]:
            if first not in MOVING_BODIES and second not in MOVING_BODIES:
                continue
            a, b = positions[first], positions[second]
            separation = eph.angular_separation(a.longitude, b.longitude)
            for aspect, (angle, orb) in eph.ASPECTS.items():
                offset = abs(separation - angle)
                if offset <= orb and (best is None or offset < best["offset"]):
                    best = {
                        "a": first, "b": second, "aspect": aspect,
                        "offset": offset,
                        "aGlyph": _text(GLYPHS.get(first, "")),
                        "bGlyph": _text(GLYPHS.get(second, "")),
                        "aspectGlyph": _text(ASPECT_GLYPHS.get(aspect, "")),
                        "aSign": a.sign, "bSign": b.sign,
                        "exact": _dms(offset),
                        "sense": ASPECT_SENSE.get(aspect, ""),
                    }
    return best


def _headline(moon: eph.Position, phase: dict, aspect: dict | None) -> str:
    """One factual sentence about the sky, with no claim about the reader."""
    lunar = f"{phase['name']} in {moon.sign}, {phase['illuminationPercent']}% lit"

    if aspect is None:
        return (
            f"{lunar}. No major planetary aspect is within orb today — "
            f"an unusually quiet sky."
        )

    return (
        f"{lunar}. {aspect['a']} and {aspect['b']} are {aspect['exact']} from "
        f"an exact {aspect['aspect']} — {aspect['sense']}."
    )


def snapshot(moment: dt.datetime | None = None) -> dict:
    """The whole live-sky payload."""
    moment = moment or _now()
    jd = eph.julian_day(moment)

    positions = {
        name: eph.position(jd, name, body_id)
        for name, body_id in eph.PLANETS
        if name != "North Node"
    }

    sun, moon = positions["Sun"], positions["Moon"]
    phase = moon_phase(sun.longitude, moon.longitude)
    aspect = tightest_aspect(positions)

    return {
        "computedAt": moment.isoformat(),
        "moon": {
            "sign": moon.sign,
            "signGlyph": _text(SIGN_GLYPHS.get(moon.sign, "")),
            "display": moon.display,
            "glyph": _text(GLYPHS["Moon"]),
            "phase": phase,
            "path": moon_path(phase["illumination"], phase["waxing"]),
        },
        "sun": {
            "sign": sun.sign,
            "signGlyph": _text(SIGN_GLYPHS.get(sun.sign, "")),
            "display": sun.display,
            "glyph": _text(GLYPHS["Sun"]),
        },
        "mercury": mercury_status(moment, positions["Mercury"]),
        "aspect": aspect,
        "headline": _headline(moon, phase, aspect),
        "positions": [
            {
                "body": name,
                "glyph": _text(GLYPHS.get(name, "")),
                "sign": p.sign,
                "signGlyph": _text(SIGN_GLYPHS.get(p.sign, "")),
                "display": p.display,
                "retrograde": p.retrograde,
            }
            for name, p in positions.items()
        ],
    }


def cached_snapshot() -> dict:
    """``snapshot`` behind a short cache.

    The landing page is the most-hit route in the app and the Moon does not
    move enough in ten minutes to change anything on screen. Recomputing per
    visitor would be the single most wasteful thing the server does.
    """
    global _cache
    with _lock:
        now = _now()
        if _cache is not None:
            computed, payload = _cache
            if (now - computed).total_seconds() < CACHE_SECONDS:
                return payload
        payload = snapshot(now)
        _cache = (now, payload)
        return payload


def reset_cache() -> None:
    """Drop the cached snapshot. Used by tests."""
    global _cache
    with _lock:
        _cache = None


__all__ = [
    "GLYPHS", "SIGN_GLYPHS", "ASPECT_GLYPHS", "PHASES", "TEXT",
    "snapshot", "cached_snapshot", "reset_cache",
    "moon_phase", "moon_path", "mercury_status", "tightest_aspect",
]
