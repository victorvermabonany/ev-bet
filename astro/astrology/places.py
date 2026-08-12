"""Birth place lookup: city name -> coordinates -> timezone -> UTC.

Runs entirely offline. Birth data is sensitive, and a chart is worthless if the
network is down, so we ship the city database rather than calling a geocoder.

The timezone step matters more than it looks. A birth time is given in local
wall-clock time, and converting it to UTC requires knowing the offset *that was
in force at that place on that date* -- including historical DST rules that have
since changed. Getting this wrong shifts the whole chart: the Ascendant moves
about a degree every four minutes, so a one-hour error moves it 15 degrees,
which is usually a different sign entirely.
"""

from __future__ import annotations

import datetime as dt
import functools
import unicodedata
from dataclasses import dataclass, asdict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import geonamescache
from timezonefinder import TimezoneFinder


@dataclass(frozen=True)
class Place:
    name: str
    country: str
    admin: str
    latitude: float
    longitude: float
    timezone: str
    population: int

    @property
    def label(self) -> str:
        parts = [self.name]
        if self.admin:
            parts.append(self.admin)
        parts.append(self.country)
        return ", ".join(parts)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["label"] = self.label
        return d


def _normalize(text: str) -> str:
    """Casefold and strip accents so 'Sao Paulo' finds 'São Paulo'."""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.casefold().strip()


@functools.lru_cache(maxsize=1)
def _timezone_finder() -> TimezoneFinder:
    return TimezoneFinder()


@functools.lru_cache(maxsize=1)
def _index() -> tuple[list[Place], dict[str, list[int]]]:
    """Build the searchable city index once, on first use."""
    cache = geonamescache.GeonamesCache()
    countries = {
        code: info["name"] for code, info in cache.get_countries().items()
    }
    us_states = {
        code: info["name"] for code, info in cache.get_us_states().items()
    }

    places: list[Place] = []
    by_name: dict[str, list[int]] = {}

    for record in cache.get_cities().values():
        country_code = record.get("countrycode", "")
        admin = ""
        if country_code == "US":
            admin = us_states.get(record.get("admin1code", ""), "")

        place = Place(
            name=record["name"],
            country=countries.get(country_code, country_code),
            admin=admin,
            latitude=float(record["latitude"]),
            longitude=float(record["longitude"]),
            timezone=record.get("timezone", "") or "",
            population=int(record.get("population", 0) or 0),
        )
        index = len(places)
        places.append(place)

        aliases = {place.name}
        aliases.update(record.get("alternatenames") or [])
        for alias in aliases:
            if not alias:
                continue
            by_name.setdefault(_normalize(alias), []).append(index)

    return places, by_name


def search(query: str, limit: int = 8) -> list[Place]:
    """Find candidate birth places, most prominent first.

    Accepts "Austin", "Austin, TX", or "Austin, Texas, United States". Results
    are ranked by population because a user typing "Springfield" almost always
    means the largest one, and the ambiguous cases are disambiguated by the
    user picking from the returned list.
    """
    query = (query or "").strip()
    if len(query) < 2:
        return []

    places, by_name = _index()
    parts = [p.strip() for p in query.split(",") if p.strip()]
    city = _normalize(parts[0])
    qualifiers = [_normalize(p) for p in parts[1:]]

    # Exact hits on any indexed name, primary or alternate.
    exact_ids = set(by_name.get(city, []))
    candidates = set(exact_ids)
    if not candidates:
        # Prefix fall-back for partial typing ("San Franc").
        for name, indexes in by_name.items():
            if name.startswith(city):
                candidates.update(indexes)
                if len(candidates) > 400:
                    break

    results = [places[i] for i in candidates]

    if qualifiers:
        def matches(place: Place) -> bool:
            haystack = _normalize(f"{place.admin} {place.country}")
            return all(q in haystack for q in qualifiers)

        narrowed = [p for p in results if matches(p)]
        if narrowed:
            results = narrowed

    def rank(place: Place) -> tuple[int, int, int]:
        """Match quality first, size second.

        Ranking prefix matches on population alone let a large city whose
        *alternate* name matched outrank the city the user was actually typing:
        "San Fr" returned Quito, because Quito's alternate name is "San
        Francisco de Quito" and it is the bigger city. A place whose own name
        matches must always come first.
        """
        name = _normalize(place.name)
        if name == city:
            tier = 0                       # its real name is exactly this
        elif name.startswith(city):
            tier = 1                       # its real name starts with this
        elif id(place) in _exact_alias_ids:
            tier = 2                       # an alternate name is exactly this
        else:
            tier = 3                       # only an alternate name starts with it
        # Closeness only means something for a prefix match, where a shorter
        # name is nearer to what was typed. For an exact hit the name's length
        # is irrelevant -- "NYC" matches both Manhattan and New York City
        # exactly, and the bigger one is the one meant.
        closeness = len(name) - len(city) if tier in (1, 3) else 0
        return (tier, closeness, -place.population)

    _exact_alias_ids = {id(places[i]) for i in exact_ids}

    results.sort(key=rank)
    return results[:limit]


def timezone_for(latitude: float, longitude: float, fallback: str = "") -> str:
    """IANA timezone for a coordinate pair."""
    name = _timezone_finder().timezone_at(lat=latitude, lng=longitude)
    if name:
        return name
    if fallback:
        return fallback
    # Mid-ocean coordinates have no timezone; approximate from longitude so a
    # chart can still be produced rather than failing outright.
    offset = round(longitude / 15.0)
    offset = max(-12, min(14, offset))
    return f"Etc/GMT{-offset:+d}"


@dataclass(frozen=True)
class ResolvedMoment:
    """A birth moment resolved to UTC, with the offset actually applied."""

    local: dt.datetime
    utc: dt.datetime
    timezone: str
    utc_offset_hours: float
    dst_in_effect: bool


def resolve_moment(
    birth_date: dt.date,
    birth_time: dt.time,
    timezone_name: str,
) -> ResolvedMoment:
    """Convert local birth date/time into UTC using historical timezone rules.

    Ambiguous times (the repeated hour when clocks go back) resolve to the
    first, pre-transition occurrence; nonexistent times (the skipped hour when
    clocks go forward) are shifted forward by ``fold`` semantics. Both are
    one-hour edge cases affecting a sliver of birth times, and both are better
    than refusing to draw a chart.
    """
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone: {timezone_name}") from exc

    local = dt.datetime.combine(birth_date, birth_time).replace(tzinfo=zone)
    offset = local.utcoffset() or dt.timedelta(0)
    dst = local.dst() or dt.timedelta(0)

    return ResolvedMoment(
        local=local,
        utc=local.astimezone(dt.timezone.utc),
        timezone=timezone_name,
        utc_offset_hours=offset.total_seconds() / 3600.0,
        dst_in_effect=dst != dt.timedelta(0),
    )


__all__ = ["Place", "ResolvedMoment", "search", "timezone_for", "resolve_moment"]
