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
def cold():
    """Reset the module to its just-imported state."""
    saved_index, saved_tf = places._index_cache, places._tf_cache
    places._index_cache = None
    places._tf_cache = None
    yield
    places._index_cache, places._tf_cache = saved_index, saved_tf


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


def test_warm_prepares_both_datasets(cold):
    assert places._index_cache is None
    places.warm()
    assert places._index_cache is not None
    assert places._tf_cache is not None
    # And it is genuinely usable afterwards.
    assert places.search("Lisbon", 1)[0].country == "Portugal"


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
