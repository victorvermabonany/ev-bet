"""Cold-worker tests.

These cover the failure that took the deployed site down: a gunicorn worker
starts with nothing loaded, several first requests arrive at once, and each one
builds its own copy of the 34k-city index. Four concurrent builds peaked at
544 MB against Render's 512 MB instance, the worker was OOM-killed, and the
in-flight requests died -- surfacing as a failed city lookup and a 502.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from astrology import places  # noqa: E402


@pytest.fixture
def cold(monkeypatch):
    """A worker with nothing built AND no precomputed file.

    This is the in-memory fallback path -- what every deployment used to do on
    every cold start, and what a fresh checkout still does before
    scripts/build_place_index.py has run.
    """
    saved_index, saved_tf, saved_db = (
        places._index_cache, places._tf_cache, places._db
    )
    places._index_cache = None
    places._tf_cache = None
    places._db = None
    monkeypatch.setattr(places, "INDEX_PATH", "/nonexistent/places.sqlite")
    yield
    places._index_cache, places._tf_cache, places._db = (
        saved_index, saved_tf, saved_db
    )


@pytest.fixture
def prebuilt():
    """A worker with the precomputed index available -- the deployed path."""
    if not os.path.exists(places.INDEX_PATH):
        pytest.skip("run scripts/build_place_index.py first")
    yield


def test_concurrent_cold_requests_build_the_index_once(cold, monkeypatch):
    """The whole bug in one assertion.

    lru_cache guards its dict, not the function body, so every thread that
    arrives before the first build finishes runs its own.
    """
    builds = []
    original = places._build_index

    def counting():
        builds.append(threading.current_thread().name)
        return original()

    monkeypatch.setattr(places, "_build_index", counting)

    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(
            lambda q: places.search(q, 3),
            ["New York", "London", "Paris", "Berlin", "Tokyo", "Lagos"],
        ))

    assert len(builds) == 1, f"index built {len(builds)} times concurrently"
    assert all(r for r in results), "every concurrent caller still got results"


def test_warm_does_not_load_the_timezone_dataset(prebuilt):
    """It costs ~41 MB and only raw coordinates need it.

    Every result the picker returns already carries its own timezone, so paying
    for this at boot is 41 MB spent for nothing on a 512 MB instance.
    """
    places._tf_cache = None
    places.warm()
    assert places._tf_cache is None


def test_timezone_finder_is_built_once(cold, monkeypatch):
    builds = []
    from timezonefinder import TimezoneFinder

    def counting():
        builds.append(1)
        return TimezoneFinder()

    monkeypatch.setattr(places, "TimezoneFinder", counting)

    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda _: places._timezone_finder(), range(4)))

    assert len(builds) == 1


def test_warm_builds_the_index_when_there_is_no_precomputed_file(cold):
    assert places._index_cache is None
    places.warm()
    assert places._index_cache is not None
    assert places.warm_stage() == "ready"
    assert places.search("Lisbon", 1)[0].country == "Portugal"


def test_warm_is_instant_when_the_index_was_precomputed(prebuilt):
    """The deployed path: opening a file, not assembling 190k dict keys."""
    started = time.time()
    places.warm()
    assert places.is_warm()
    assert places.warm_stage() == "ready"
    assert time.time() - started < 1.0, "warm-up should be a file open"
    # And nothing was built in memory to achieve it.
    assert places._index_cache is None


def test_both_lookup_paths_agree(prebuilt, monkeypatch):
    """The fallback must not quietly return different cities to the real path."""
    queries = ["New York", "NYC", "San Fr", "Bombay", "Dubl", "Austin, TX", "Lisb"]
    from_db = {q: [p.label for p in places.search(q, 5)] for q in queries}

    saved_db, saved_index = places._db, places._index_cache
    try:
        places._db = None
        places._index_cache = None
        monkeypatch.setattr(places, "INDEX_PATH", "/nonexistent/places.sqlite")
        from_memory = {q: [p.label for p in places.search(q, 5)] for q in queries}
    finally:
        places._db, places._index_cache = saved_db, saved_index

    for query in queries:
        assert from_db[query] == from_memory[query], query


def test_a_second_search_does_not_rebuild(cold, monkeypatch):
    builds = []
    original = places._build_index
    monkeypatch.setattr(places, "_build_index",
                        lambda: (builds.append(1), original())[1])

    places.search("Oslo", 1)
    places.search("Madrid", 1)
    places.search("Cairo", 1)
    assert len(builds) == 1


def test_the_app_warms_datasets_without_being_run_as_main():
    """gunicorn imports the module; it never executes __main__.

    The warm-up used to live there, so in production nothing was ever warmed
    and the first user keystroke paid for the whole build.
    """
    source = open(os.path.join(os.path.dirname(__file__), "..", "app.py")).read()

    main_block = source.split('if __name__ == "__main__":')[1]
    assert "places.warm" not in main_block
    assert "places.search" not in main_block, "warm-up must not sit under __main__"

    # It is called at import instead.
    before_main = source.split('if __name__ == "__main__":')[0]
    assert "_warm_datasets()" in before_main


def test_warm_up_failure_does_not_take_the_worker_down(monkeypatch, capsys):
    """A dataset problem should degrade to a slow first request, not a crash."""
    import app as app_module

    def explode():
        raise RuntimeError("simulated dataset failure")

    monkeypatch.setattr(places, "warm", explode)
    app_module._warm_datasets()           # must not raise
    time.sleep(0.3)                        # let the daemon thread run

    # The app still answers.
    app_module.app.config["TESTING"] = True
    assert app_module.app.test_client().get("/health").status_code == 200


def test_a_stale_index_is_ignored_rather_than_answering_wrongly(prebuilt, monkeypatch, tmp_path):
    """If _normalize changes, the prebuilt keys stop corresponding to queries.

    The file is not corrupt -- it answers a question nobody asks any more, so
    every lookup would silently miss. It must be rejected, not trusted.
    """
    import shutil
    import sqlite3

    stale = tmp_path / "stale.sqlite"
    shutil.copy(places.INDEX_PATH, stale)
    conn = sqlite3.connect(stale)
    conn.execute("UPDATE meta SET value = 'a-different-normalizer'")
    conn.commit()
    conn.close()

    saved_db = places._db
    try:
        places._db = None
        monkeypatch.setattr(places, "INDEX_PATH", str(stale))
        assert places._database() is None, "stale index must be rejected"
        # And the app still works, via the in-memory fallback.
        places._index_cache = None
        assert places.search("Lisbon", 1)[0].country == "Portugal"
    finally:
        places._db = saved_db
        places._index_cache = None


def test_the_committed_index_matches_the_current_normalizer(prebuilt):
    """Guards against committing code that invalidates the checked-in file."""
    assert places._database() is not None, (
        "data/places.sqlite is stale — re-run scripts/build_place_index.py"
    )
