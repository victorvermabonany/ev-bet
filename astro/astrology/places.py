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
import os
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass, asdict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import geonamescache
from timezonefinder import TimezoneFinder


@dataclass(frozen=True, slots=True)
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


# Both datasets are expensive to build and must be built exactly once.
#
# functools.lru_cache was not enough: it only guards the cache dict, not the
# function body, so concurrent threads each run the build and keep their own
# copy. On a cold gunicorn worker -- which is every Render cold start, since
# the warm-up used to live under `if __name__ == "__main__"` and gunicorn never
# runs that -- four overlapping first requests built the 34k-city index four
# times and peaked at 544 MB against a 512 MB instance. The worker was
# OOM-killed, which is what surfaced as a failed city lookup and a 502.
_index_lock = threading.Lock()
_index_cache: tuple[list["Place"], dict[str, list[int]]] | None = None

_tf_lock = threading.Lock()
_tf_cache: TimezoneFinder | None = None


def _timezone_finder() -> TimezoneFinder:
    global _tf_cache
    if _tf_cache is None:
        with _tf_lock:
            if _tf_cache is None:
                _tf_cache = TimezoneFinder()
    return _tf_cache


def _index() -> tuple[list[Place], dict[str, list[int]]]:
    """The city index, built once however many callers arrive at once."""
    global _index_cache
    if _index_cache is None:
        with _index_lock:
            if _index_cache is None:
                _index_cache = _build_index()
    return _index_cache


# Where the precomputed index lives. Built by scripts/build_place_index.py at
# deploy time; absent in a fresh checkout, in which case the in-memory build
# below takes over so local development and the tests need no build step.
INDEX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "places.sqlite"
)

_db_lock = threading.Lock()
_db: sqlite3.Connection | None = None

_warm_stage = "cold"


def _database() -> sqlite3.Connection | None:
    """The precomputed index, or None if this deployment has no built file."""
    global _db
    if _db is None:
        if not os.path.exists(INDEX_PATH):
            return None
        with _db_lock:
            if _db is None:
                _db = sqlite3.connect(INDEX_PATH, check_same_thread=False)
                _db.row_factory = sqlite3.Row
    return _db


def _place_from_row(row) -> Place:
    return Place(
        name=row["name"], country=row["country"], admin=row["admin"],
        latitude=row["latitude"], longitude=row["longitude"],
        timezone=row["timezone"], population=row["population"],
    )


def _search_db(conn: sqlite3.Connection, city: str, limit: int) -> list[tuple[Place, bool]]:
    """Candidates for ``city``, each flagged as an exact-name hit.

    Exact matches first, and only if there are none does it range-scan the
    prefix -- `key >= q AND key < q + '\uffff'` rather than LIKE, so the index
    is always used.
    """
    # GROUP BY p.id is load-bearing: a city can carry several names matching the
    # same prefix ("san francisco", "san francisco de asis"), and the join
    # yields one row per name. Without it "San Fr" returned San Francisco five
    # times. The in-memory path deduped via a set of ids.
    rows = conn.execute(
        "SELECT p.* FROM names n JOIN places p ON p.id = n.place_id "
        "WHERE n.key = ? GROUP BY p.id ORDER BY p.population DESC LIMIT ?",
        (city, limit * 4),
    ).fetchall()
    if rows:
        return [(_place_from_row(r), True) for r in rows]

    rows = conn.execute(
        "SELECT p.* FROM names n JOIN places p ON p.id = n.place_id "
        "WHERE n.key >= ? AND n.key < ? GROUP BY p.id "
        "ORDER BY p.population DESC LIMIT ?",
        (city, city + "\uffff", 400),
    ).fetchall()
    return [(_place_from_row(r), False) for r in rows]


def is_warm() -> bool:
    """True once a search will not have to wait for anything to be built."""
    return _database() is not None or _index_cache is not None


def warm_stage() -> str:
    """Where the background warm-up has got to.

    Render's free tier runs at a fraction of a CPU, so a build that takes a
    second locally can take far longer there. Reporting the stage turns "it is
    hanging" into "it is on the timezone dataset".
    """
    return _warm_stage


def warm() -> None:
    """Make the first request cheap.

    With the precomputed file this is just opening SQLite -- instant, and a
    megabyte. Without it we fall back to assembling the index in memory, which
    is what this used to do on every deployment.

    The timezone dataset is deliberately *not* warmed: it costs ~41 MB and is
    only consulted for raw coordinates with no timezone attached, which the
    picker never produces because every result carries its own.
    """
    global _warm_stage
    if _database() is not None:
        _warm_stage = "ready"
        return
    _warm_stage = "building city index in memory (no precomputed file)"
    _index()
    _warm_stage = "ready"


def _build_index() -> tuple[list[Place], dict[str, list[int]]]:
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

        # The dataset carries 353k alternate names across every script it has
        # ever been transliterated into -- Cyrillic, Han, Arabic, Devanagari.
        # Indexing all of them cost ~150 MB and most of the build time, to match
        # spellings nobody types into an English form. Keeping the ASCII ones
        # halves the index while leaving the aliases that matter (NYC, Bombay,
        # Calcutta, Munchen) intact, and accented spellings still resolve
        # because _normalize strips the accents anyway.
        by_name.setdefault(_normalize(place.name), []).append(index)
        for alias in record.get("alternatenames") or ():
            if not alias or not alias.isascii() or not 2 <= len(alias) <= 40:
                continue
            key = _normalize(alias)
            bucket = by_name.setdefault(key, [])
            if not bucket or bucket[-1] != index:
                bucket.append(index)

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

    parts = [p.strip() for p in query.split(",") if p.strip()]
    city = _normalize(parts[0])
    qualifiers = [_normalize(p) for p in parts[1:]]

    conn = _database()
    if conn is not None:
        return _rank(_search_db(conn, city, limit), city, qualifiers, limit)

    # No precomputed file (fresh checkout, tests): build the index in memory.
    places, by_name = _index()
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
    exact_names = {id(places[i]) for i in exact_ids}
    return _rank(
        [(p, id(p) in exact_names) for p in results], city, qualifiers, limit
    )


def _rank(
    candidates: list[tuple[Place, bool]],
    city: str,
    qualifiers: list[str],
    limit: int,
) -> list[Place]:
    """Order candidates by how well they match, then by size.

    Ranking on population alone let a large city whose *alternate* name matched
    outrank the one being typed: "San Fr" returned Quito, whose alternate name
    is "San Francisco de Quito". A place whose own name matches must win.
    """
    if qualifiers:
        def fits(place: Place) -> bool:
            haystack = _normalize(f"{place.admin} {place.country}")
            return all(q in haystack for q in qualifiers)

        narrowed = [c for c in candidates if fits(c[0])]
        if narrowed:
            candidates = narrowed

    def key(entry: tuple[Place, bool]) -> tuple[int, int, int]:
        place, exact_hit = entry
        name = _normalize(place.name)
        if name == city:
            tier = 0                       # its real name is exactly this
        elif name.startswith(city):
            tier = 1                       # its real name starts with this
        elif exact_hit:
            tier = 2                       # an alternate name is exactly this
        else:
            tier = 3                       # only an alternate name starts with it
        # Closeness only means something for a prefix match. For an exact hit
        # the name's length is irrelevant -- "NYC" matches both Manhattan and
        # New York City exactly, and the bigger one is the one meant.
        closeness = len(name) - len(city) if tier in (1, 3) else 0
        return (tier, closeness, -place.population)

    candidates.sort(key=key)
    return [place for place, _ in candidates[:limit]]


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


__all__ = ["Place", "ResolvedMoment", "search", "timezone_for", "resolve_moment",
           "warm", "is_warm", "warm_stage"]
