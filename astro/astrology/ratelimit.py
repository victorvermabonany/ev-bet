"""A small in-process rate limiter.

The app runs a single gunicorn worker, so a plain dict is a correct shared
counter and a dependency like flask-limiter (which wants Redis to be useful)
would buy nothing. If the deployment ever grows a second worker this becomes
per-worker -- generous rather than wrong -- and that is the point to move the
counters into Redis.

Fixed windows rather than a token bucket: the thing being protected is a
per-hour spend ceiling, and a window that resets on the hour is far easier to
reason about when someone asks "how much can one person cost me".
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
# (bucket_name, identity) -> [window_started_at, count]
_counters: dict[tuple[str, str], list] = {}

# Stop the dict growing without bound on a long-lived process. Cleared lazily
# on write, so there is no background thread to manage.
_MAX_TRACKED = 20_000


class Decision:
    """The outcome of one rate-limit check."""

    __slots__ = ("allowed", "limit", "remaining", "retry_after")

    def __init__(self, allowed: bool, limit: int, remaining: int, retry_after: int):
        self.allowed = allowed
        self.limit = limit
        self.remaining = remaining
        self.retry_after = retry_after

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"Decision(allowed={self.allowed}, limit={self.limit}, "
            f"remaining={self.remaining}, retry_after={self.retry_after})"
        )


def check(bucket: str, identity: str, limit: int, window_seconds: int, now=None) -> Decision:
    """Count one request against ``bucket`` for ``identity``.

    ``now`` is injectable so the tests can advance time without sleeping.
    """
    moment = time.time() if now is None else now
    key = (bucket, identity or "-")

    with _lock:
        if len(_counters) > _MAX_TRACKED:
            _sweep(moment)

        entry = _counters.get(key)
        if entry is None or moment - entry[0] >= window_seconds:
            entry = [moment, 0]
            _counters[key] = entry

        if entry[1] >= limit:
            elapsed = moment - entry[0]
            retry_after = max(1, int(window_seconds - elapsed) + 1)
            return Decision(False, limit, 0, retry_after)

        entry[1] += 1
        return Decision(True, limit, limit - entry[1], 0)


def _sweep(moment: float) -> None:
    """Drop counters whose window is long past. Caller holds the lock."""
    stale = [k for k, v in _counters.items() if moment - v[0] > 86_400]
    for key in stale:
        _counters.pop(key, None)
    if len(_counters) > _MAX_TRACKED:
        _counters.clear()


def reset() -> None:
    """Forget every counter. Used by tests and by nothing else."""
    with _lock:
        _counters.clear()


__all__ = ["Decision", "check", "reset"]
