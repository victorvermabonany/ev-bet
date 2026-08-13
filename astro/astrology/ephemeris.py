"""Low-level Swiss Ephemeris wrapper.

Everything in this module is real astronomy: positions come from the Swiss
Ephemeris (Moshier analytical ephemeris, accurate to well under an arcminute
for any modern birth date). Nothing here is interpretive -- interpretation
happens later, on top of these numbers.

Longitudes are tropical (equinox of date), measured in degrees 0-360 from the
vernal point, which is the frame Western astrology uses.
"""

from __future__ import annotations

import datetime as dt
import math
import threading
from dataclasses import dataclass, asdict

import swisseph as swe

# Moshier: analytical, self-contained, no .se1 data files to ship.
CALC_FLAGS = swe.FLG_SWIEPH | swe.FLG_SPEED | swe.FLG_MOSEPH

SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
]

# The bodies a career reading actually leans on. Chiron and the outer-planet
# nodes are deliberately excluded: they add noise without adding signal for
# work questions, and Chiron needs a separate ephemeris file.
PLANETS = [
    ("Sun", swe.SUN),
    ("Moon", swe.MOON),
    ("Mercury", swe.MERCURY),
    ("Venus", swe.VENUS),
    ("Mars", swe.MARS),
    ("Jupiter", swe.JUPITER),
    ("Saturn", swe.SATURN),
    ("Uranus", swe.URANUS),
    ("Neptune", swe.NEPTUNE),
    ("Pluto", swe.PLUTO),
    ("North Node", swe.TRUE_NODE),
]

# pyswisseph wraps a C library with global state (ephemeris path, sidereal
# mode). Serialize access so concurrent web requests can't interleave inside it.
_swe_lock = threading.Lock()


class EphemerisError(RuntimeError):
    """Raised when the underlying ephemeris cannot produce a position."""


@dataclass(frozen=True)
class Position:
    """One body's position at one moment."""

    body: str
    longitude: float          # tropical ecliptic longitude, 0-360
    latitude: float           # ecliptic latitude
    speed: float              # degrees/day; negative means retrograde
    sign: str
    degree_in_sign: float     # 0-30
    retrograde: bool

    @property
    def display(self) -> str:
        deg = int(self.degree_in_sign)
        minutes = int(round((self.degree_in_sign - deg) * 60))
        if minutes == 60:  # carry, so we never print 12°60'
            deg, minutes = deg + 1, 0
        rx = " Rx" if self.retrograde else ""
        return f"{deg}°{minutes:02d}' {self.sign}{rx}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["display"] = self.display
        return d


def julian_day(moment_utc: dt.datetime) -> float:
    """Julian day (UT) for a timezone-aware UTC datetime."""
    if moment_utc.tzinfo is None:
        raise ValueError("moment_utc must be timezone-aware")
    moment_utc = moment_utc.astimezone(dt.timezone.utc)
    hour = (
        moment_utc.hour
        + moment_utc.minute / 60
        + (moment_utc.second + moment_utc.microsecond / 1e6) / 3600
    )
    return swe.julday(moment_utc.year, moment_utc.month, moment_utc.day, hour)


def sign_of(longitude: float) -> tuple[str, float]:
    """Split an absolute longitude into (sign name, degrees into that sign)."""
    longitude %= 360.0
    index = int(longitude // 30)
    return SIGNS[index], longitude - index * 30


def position(jd_ut: float, body_name: str, body_id: int) -> Position:
    with _swe_lock:
        try:
            values, ret_flag = swe.calc_ut(jd_ut, body_id, CALC_FLAGS)
        except swe.Error as exc:  # pragma: no cover - defensive
            raise EphemerisError(f"{body_name}: {exc}") from exc
    if ret_flag < 0:  # pragma: no cover - defensive
        raise EphemerisError(f"{body_name}: ephemeris returned {ret_flag}")

    longitude, latitude, _distance, speed = values[0], values[1], values[2], values[3]
    sign, degree_in_sign = sign_of(longitude)
    return Position(
        body=body_name,
        longitude=longitude % 360.0,
        latitude=latitude,
        speed=speed,
        sign=sign,
        degree_in_sign=degree_in_sign,
        retrograde=speed < 0,
    )


def raw(jd_ut: float, body_id: int) -> tuple[float, float]:
    """Fast path: just (longitude, speed), no dataclass or formatting.

    The timing scans call this tens of thousands of times per request, where
    building a full :class:`Position` for each sample dominates the runtime.
    """
    with _swe_lock:
        values, ret_flag = swe.calc_ut(jd_ut, body_id, CALC_FLAGS)
    if ret_flag < 0:  # pragma: no cover - defensive
        raise EphemerisError(f"body {body_id}: ephemeris returned {ret_flag}")
    return values[0] % 360.0, values[3]


def all_positions(jd_ut: float) -> dict[str, Position]:
    return {name: position(jd_ut, name, body_id) for name, body_id in PLANETS}


@dataclass(frozen=True)
class Houses:
    """House cusps and angles.

    ``cusps`` is 1-indexed conceptually but stored as a 12-element list where
    index 0 is the 1st house (the Ascendant).
    """

    system: str
    cusps: list[float]
    ascendant: float
    midheaven: float

    def cusp(self, house: int) -> float:
        if not 1 <= house <= 12:
            raise ValueError("house must be 1-12")
        return self.cusps[house - 1]

    def house_of(self, longitude: float) -> int:
        """Which house a given longitude falls in.

        Houses are unequal in Placidus, and the ring wraps at 0 Aries, so this
        walks cusp-to-cusp using forward arc length rather than comparing
        raw longitudes.
        """
        longitude %= 360.0
        for i in range(12):
            start = self.cusps[i]
            end = self.cusps[(i + 1) % 12]
            span = (end - start) % 360.0
            offset = (longitude - start) % 360.0
            if offset < span:
                return i + 1
        return 12  # pragma: no cover - unreachable for a valid cusp ring


def houses(
    jd_ut: float,
    latitude: float,
    longitude: float,
    system: str = "placidus",
) -> Houses:
    """Compute house cusps.

    Placidus is the default because it is what the overwhelming majority of
    modern Western astrology (and every app we are competing with) uses, so a
    user comparing our chart against another app's sees the same 10th house.
    Placidus is undefined inside the polar circles; we fall back to Whole Sign
    there rather than emitting garbage cusps.
    """
    codes = {"placidus": b"P", "whole_sign": b"W", "koch": b"K", "equal": b"A"}
    if system not in codes:
        raise ValueError(f"unsupported house system: {system}")

    effective = system
    if system == "placidus" and abs(latitude) > 66.0:
        effective = "whole_sign"

    with _swe_lock:
        try:
            cusps, ascmc = swe.houses(jd_ut, latitude, longitude, codes[effective])
        except swe.Error as exc:  # pragma: no cover - defensive
            raise EphemerisError(f"houses: {exc}") from exc

    return Houses(
        system=effective,
        cusps=[c % 360.0 for c in cusps[:12]],
        ascendant=ascmc[0] % 360.0,
        midheaven=ascmc[1] % 360.0,
    )


def angular_separation(a: float, b: float) -> float:
    """Shortest angular distance between two longitudes, 0-180."""
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


# Aspect name -> (exact angle, default orb in degrees).
ASPECTS = {
    "conjunction": (0.0, 8.0),
    "opposition": (180.0, 8.0),
    "trine": (120.0, 7.0),
    "square": (90.0, 7.0),
    "sextile": (60.0, 5.0),
}


@dataclass(frozen=True)
class Aspect:
    body_a: str
    body_b: str
    aspect: str
    exact_angle: float
    orb: float          # how far from exact, in degrees
    applying: bool      # tightening (more potent) vs separating

    def to_dict(self) -> dict:
        return asdict(self)


def find_aspects(
    positions_a: dict[str, Position],
    positions_b: dict[str, Position] | None = None,
    orb_scale: float = 1.0,
) -> list[Aspect]:
    """Find aspects within a chart, or between two charts.

    With one argument, returns natal aspects (each pair once). With two, treats
    ``positions_a`` as the moving set (transits) against ``positions_b``
    (natal), which is the asymmetric case, so every pair is checked.
    """
    cross = positions_b is not None
    target = positions_b if cross else positions_a

    pairs = []
    if cross:
        pairs = [(a, b) for a in positions_a.values() for b in target.values()]
    else:
        names = list(positions_a)
        pairs = [
            (positions_a[names[i]], positions_a[names[j]])
            for i in range(len(names))
            for j in range(i + 1, len(names))
        ]

    found: list[Aspect] = []
    for a, b in pairs:
        separation = angular_separation(a.longitude, b.longitude)
        for name, (angle, base_orb) in ASPECTS.items():
            orb = abs(separation - angle)
            if orb > base_orb * orb_scale:
                continue
            found.append(
                Aspect(
                    body_a=a.body,
                    body_b=b.body,
                    aspect=name,
                    exact_angle=angle,
                    orb=orb,
                    applying=_is_applying(a, b, angle, cross=cross),
                )
            )
            break  # a pair can only hold one aspect at a time
    found.sort(key=lambda x: x.orb)
    return found


def _is_applying(a: Position, b: Position, angle: float, cross: bool) -> bool:
    """Whether the aspect is tightening.

    Nudge both bodies forward by a small time step and see whether the orb
    shrinks. In the cross-chart (transit) case the natal body is fixed, so only
    the transiting body moves. This handles retrogrades without special-casing.
    """
    step = 0.01  # days
    a_next = a.longitude + a.speed * step
    b_next = b.longitude + (0.0 if cross else b.speed * step)
    now = abs(angular_separation(a.longitude, b.longitude) - angle)
    later = abs(angular_separation(a_next, b_next) - angle)
    return later < now


def solar_return_jd(natal_jd: float, natal_sun_longitude: float, year: int) -> float:
    """Julian day the Sun next returns to its natal longitude in ``year``.

    Used for the annual "birthday chart" that anchors year-ahead timing.
    Bisection on the unwrapped angular difference; the Sun's motion is
    monotonic so this always converges.
    """
    start = swe.julday(year, 1, 1, 0.0)
    lo, hi = start, start + 366.0

    def delta(jd: float) -> float:
        sun = position(jd, "Sun", swe.SUN).longitude
        return ((sun - natal_sun_longitude + 180.0) % 360.0) - 180.0

    # Scan day by day for the sign change, then bisect inside that day.
    prev_jd, prev = lo, delta(lo)
    jd = lo
    while jd < hi:
        jd += 1.0
        current = delta(jd)
        if prev <= 0 <= current:
            lo, hi = prev_jd, jd
            break
        prev_jd, prev = jd, current
    else:  # pragma: no cover - a solar return always exists in a 366-day span
        raise EphemerisError("no solar return found in window")

    for _ in range(60):
        mid = (lo + hi) / 2
        if delta(lo) * delta(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def next_station(jd_ut: float, body_name: str, body_id: int, limit_days: int = 400):
    """Next time ``body`` changes direction, or None inside the window.

    Returns ``(julian_day, "retrograde"|"direct")``. This is what powers
    "Mercury turns retrograde on the 12th -- sign after that, not before".
    """
    step = 0.5
    current = position(jd_ut, body_name, body_id).speed
    jd = jd_ut
    while jd < jd_ut + limit_days:
        jd += step
        speed = position(jd, body_name, body_id).speed
        if (speed < 0) != (current < 0):
            lo, hi = jd - step, jd
            for _ in range(40):
                mid = (lo + hi) / 2
                if (position(mid, body_name, body_id).speed < 0) == (current < 0):
                    lo = mid
                else:
                    hi = mid
            station = (lo + hi) / 2
            return station, ("retrograde" if speed < 0 else "direct")
        current = speed
    return None


def jd_to_datetime(jd_ut: float) -> dt.datetime:
    """Inverse of :func:`julian_day`, returning an aware UTC datetime."""
    year, month, day, hour = swe.revjul(jd_ut)
    whole_hours = int(hour)
    minutes_float = (hour - whole_hours) * 60
    minutes = int(minutes_float)
    seconds = int(round((minutes_float - minutes) * 60))
    if seconds == 60:
        seconds, minutes = 0, minutes + 1
    if minutes == 60:
        minutes, whole_hours = 0, whole_hours + 1
    base = dt.datetime(year, month, day, tzinfo=dt.timezone.utc)
    return base + dt.timedelta(hours=whole_hours, minutes=minutes, seconds=seconds)


def obliquity(jd_ut: float) -> float:
    """True obliquity of the ecliptic, degrees. Used by the test harness."""
    with _swe_lock:
        values, _ = swe.calc_ut(jd_ut, swe.ECL_NUT, swe.FLG_SWIEPH | swe.FLG_MOSEPH)
    return values[0]


def sidereal_time_deg(jd_ut: float) -> float:
    """Greenwich apparent sidereal time in degrees. Used by the test harness."""
    with _swe_lock:
        return swe.sidtime(jd_ut) * 15.0


__all__ = [
    "SIGNS", "PLANETS", "Position", "Houses", "Aspect", "EphemerisError",
    "julian_day", "jd_to_datetime", "sign_of", "position", "all_positions",
    "houses", "find_aspects", "angular_separation", "solar_return_jd",
    "next_station", "obliquity", "sidereal_time_deg", "math",
]
