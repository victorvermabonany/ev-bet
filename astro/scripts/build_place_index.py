"""Precompute the city index into SQLite, at build time.

Why this exists
---------------

The index used to be built in the worker on first use: 34k cities and ~190k
searchable names assembled into Python dicts. That costs about 139 MB of
resident memory and a second or two of CPU on a fast machine. On Render's free
instance -- 512 MB and a fraction of a core, shared with everything else the
process is doing -- it was enough to stop the worker from ever finishing the
build, which is what surfaced as a dead city lookup and a 502.

Doing it here moves that work to the build step, where there is headroom and it
happens once per deploy rather than once per cold start. The worker then opens
a ~15 MB file and queries it, holding almost nothing in memory.

Run automatically by render.yaml's buildCommand. Safe to run by hand:

    python scripts/build_place_index.py

If the file is absent at runtime the app falls back to building the index in
memory, so local development and the test suite work without this step.
"""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import geonamescache  # noqa: E402

from astrology.places import INDEX_PATH, _normalize  # noqa: E402

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
"""

# Built after the inserts: filling an unindexed table and indexing once is far
# cheaper than maintaining the B-tree per row.
INDEXES = """
CREATE INDEX names_key ON names (key, place_id);
CREATE INDEX places_pop ON places (population DESC);
"""


def build(path: str = INDEX_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.remove(path)

    cache = geonamescache.GeonamesCache()
    countries = {code: info["name"] for code, info in cache.get_countries().items()}
    us_states = {code: info["name"] for code, info in cache.get_us_states().items()}

    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)

    places_rows = []
    name_rows = []

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

    conn.executemany("INSERT INTO places VALUES (?,?,?,?,?,?,?,?)", places_rows)
    conn.executemany("INSERT INTO names VALUES (?,?,?)", name_rows)
    conn.executescript(INDEXES)
    conn.commit()
    conn.execute("VACUUM")
    conn.close()

    size = os.path.getsize(path) / (1024 * 1024)
    print(f"built {path}: {len(places_rows):,} places, {len(name_rows):,} names, {size:.1f} MB")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else INDEX_PATH)
