"""Compiling the city index into SQLite.

The index used to be assembled into Python dicts on first use: 34k cities and
~196k searchable names, about 139 MB resident and seconds of CPU. On a 512 MB
instance with a fraction of a core that was enough to stop a worker finishing,
which is what took the live site down.

Compiling it into SQLite instead costs ~110 MB once, at boot, and leaves the
worker holding about a megabyte -- SQLite pages the file rather than loading
it. Built here rather than committed as an 11 MB binary, and rather than in a
build step, so a deployment has nothing extra that can fail.
"""

from __future__ import annotations

import os
import sqlite3

import geonamescache

from .places import INDEX_PATH, _normalize

SCHEMA = """
PRAGMA journal_mode = OFF;
PRAGMA synchronous = OFF;

CREATE TABLE places (
    id        INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    country   TEXT NOT NULL,
    admin     TEXT NOT NULL,
    latitude  REAL NOT NULL,
    longitude REAL NOT NULL,
    timezone  TEXT NOT NULL,
    population INTEGER NOT NULL
);

CREATE TABLE names (
    key      TEXT NOT NULL,
    place_id INTEGER NOT NULL,
    primary_name INTEGER NOT NULL
);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# The keys in `names` are whatever _normalize produced at build time. If that
# function changes, every lookup silently stops matching -- the file is not
# corrupt, it is answering a question nobody is asking any more. Fingerprinting
# it lets the app notice and fall back instead of returning nothing.
FINGERPRINT_SAMPLES = ("São Paulo", "MÜNCHEN", "  Saint-Louis  ", "NYC", "Ōsaka")


def normalizer_fingerprint(normalize) -> str:
    return "|".join(normalize(s) for s in FINGERPRINT_SAMPLES)

# Built after the inserts: filling an unindexed table and indexing once is far
# cheaper than maintaining the B-tree per row.
INDEXES = """
CREATE INDEX names_key ON names (key, place_id);
CREATE INDEX places_pop ON places (population DESC);
"""


def build(path: str = INDEX_PATH) -> None:
    """Compile the index and put it at ``path`` in one step.

    The compile writes to a sibling temporary file and renames it into place,
    because the app is serving requests while this runs. Building directly into
    ``path`` meant that for the whole of the compile there was a file at the
    destination that was not yet an index, and _database() opens whatever it
    finds there: early on it saw the empty `meta` table and logged "built with a
    different normalizer" -- sending that request into the 139 MB in-memory
    build, which is the exact thing this module exists to avoid -- and later it
    cached a connection to a database that had every row but none of its
    indexes, with a VACUUM still to rewrite the file underneath it.

    os.replace is atomic on POSIX, so a concurrent _database() now sees either
    no file at all or a finished one.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    staging = f"{path}.building.{os.getpid()}"
    for stale in (staging,):
        if os.path.exists(stale):
            os.remove(stale)

    try:
        _compile(staging)
        os.replace(staging, path)
    finally:
        if os.path.exists(staging):
            os.remove(staging)

    size = os.path.getsize(path) / (1024 * 1024)
    print(f"built {path}: {size:.1f} MB")


def _compile(path: str) -> None:
    cache = geonamescache.GeonamesCache()
    countries = {code: info["name"] for code, info in cache.get_countries().items()}
    us_states = {code: info["name"] for code, info in cache.get_us_states().items()}

    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    # Streamed in batches rather than accumulated: holding 34k place tuples and
    # ~196k name tuples alongside the source dataset roughly doubled peak
    # memory, for no benefit.
    places_rows = []
    name_rows = []
    total_places = 0
    total_names = 0

    def flush(force=False):
        nonlocal total_places, total_names
        if force or len(name_rows) > 20000:
            conn.executemany("INSERT INTO places VALUES (?,?,?,?,?,?,?,?)", places_rows)
            conn.executemany("INSERT INTO names VALUES (?,?,?)", name_rows)
            total_places += len(places_rows)
            total_names += len(name_rows)
            places_rows.clear()
            name_rows.clear()

    for index, record in enumerate(cache.get_cities().values()):
        country_code = record.get("countrycode", "")
        admin = us_states.get(record.get("admin1code", ""), "") if country_code == "US" else ""

        name = record["name"]
        places_rows.append((
            index,
            name,
            countries.get(country_code, country_code),
            admin,
            float(record["latitude"]),
            float(record["longitude"]),
            record.get("timezone", "") or "",
            int(record.get("population", 0) or 0),
        ))

        seen = set()
        primary = _normalize(name)
        name_rows.append((primary, index, 1))
        seen.add(primary)

        # ASCII aliases only. The dataset carries every transliteration a place
        # has ever had -- Cyrillic, Han, Arabic -- and indexing those matches
        # spellings nobody types into an English form. Accented spellings still
        # resolve because _normalize strips accents.
        for alias in record.get("alternatenames") or ():
            if not alias or not alias.isascii() or not 2 <= len(alias) <= 40:
                continue
            key = _normalize(alias)
            if key and key not in seen:
                name_rows.append((key, index, 0))
                seen.add(key)

        flush()

    flush(force=True)
    conn.execute(
        "INSERT INTO meta VALUES ('normalizer', ?)",
        (normalizer_fingerprint(_normalize),),
    )
    conn.executescript(INDEXES)
    conn.commit()
    conn.execute("VACUUM")
    conn.close()

    print(f"  compiled {total_places:,} places, {total_names:,} names")



__all__ = ["build", "normalizer_fingerprint", "FINGERPRINT_SAMPLES"]
