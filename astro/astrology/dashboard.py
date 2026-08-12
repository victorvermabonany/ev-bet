"""The post-signup dashboard payload.

Assembles the home screen a user lands on after their chart is calculated:
their archetype, the layers of chart data we actually read, the reading split
into sections, and the timing windows grouped into today / this week / this
month.

Two things this module is deliberately careful about.

**It does not invent systems.** The product reads one tradition -- Western
tropical astrology from the Swiss Ephemeris -- through several distinct layers.
Those layers are real and worth showing separately, because they have different
reliability (houses need a birth time; transits do not) and different meaning.
What it will not do is claim a numerology or Human Design engine that does not
exist behind it.

**The free/paid cut happens here, not in the browser.** A locked timing bucket
is sent as a count and a teaser. The actual windows are simply absent from the
free payload, so there is nothing to reveal with devtools.
"""

from __future__ import annotations

import datetime as dt

from .career import CareerProfile
from .chart import Chart


def _today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _as_date(value) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Systems: the layers of chart data this reading is actually built from
# ---------------------------------------------------------------------------


def systems(chart: Chart, profile: CareerProfile, timing: dict) -> list[dict]:
    """One card per layer of data we genuinely compute.

    ``status`` is "ready" or "needs_time" -- the house layer is the only one a
    missing birth time disables, and saying so plainly is more useful than
    hiding the card.
    """
    time_known = chart.birth.time_known
    sun = chart.positions["Sun"]
    mars = chart.positions["Mars"]
    saturn = chart.positions["Saturn"]

    windows = timing.get("windows", [])
    cycles = timing.get("cycles", [])
    retrogrades = timing.get("mercuryRetrograde", [])

    cards: list[dict] = []

    cards.append({
        "key": "placements",
        "name": "Natal placements",
        "source": "Swiss Ephemeris · tropical",
        "status": "ready",
        "read": (
            f"Your Sun sits at {sun.display} and Mars at {mars.display}. Together "
            f"they set what you are aimed at and how you push for it — the two "
            f"things a career read leans on hardest."
        ),
        "more": "chart",
    })

    if time_known:
        tenth = profile.tenth_house_bodies
        occupancy = (
            f"{', '.join(tenth)} sits in your 10th house."
            if tenth else
            "No planet occupies your 10th house, which is normal — the sign on "
            "the cusp and its ruler carry the read instead."
        )
        cards.append({
            "key": "houses",
            "name": "Houses and angles",
            "source": "Placidus · needs birth time",
            "status": "ready",
            "read": (
                f"Your Midheaven — the career point itself — is {profile.midheaven_display}. "
                f"{occupancy}"
            ),
            "more": "chart",
        })
    else:
        cards.append({
            "key": "houses",
            "name": "Houses and angles",
            "source": "Placidus · needs birth time",
            "status": "needs_time",
            "read": (
                "This layer is switched off. Houses and the Midheaven are fixed "
                "by the minute of birth, so without a time we would be guessing "
                "rather than calculating."
            ),
            "more": "time",
        })

    active = [w for w in windows if w.get("activeNow")]
    if active:
        transit_read = (
            f"{len(active)} transit is crossing your career points right now, "
            f"out of {len(windows)} mapped across the next 18 months."
            if len(active) == 1 else
            f"{len(active)} transits are crossing your career points right now, "
            f"out of {len(windows)} mapped across the next 18 months."
        )
    elif windows:
        transit_read = (
            f"Nothing is crossing your career points today. {len(windows)} windows "
            f"are mapped across the next 18 months, so the next one has a date."
        )
    else:
        transit_read = (
            "No slow-planet contact to your career points in the next 18 months. "
            "Quiet stretches are for building rather than forcing a move."
        )

    cards.append({
        "key": "transits",
        "name": "Current transits",
        "source": "today's sky against your chart",
        "status": "ready",
        "read": transit_read,
        "more": "timing",
    })

    current = [c for c in cycles if c.get("status") == "current"]
    if current:
        cycle_read = (
            f"You are inside your {current[0].get('name', 'return')} right now — "
            f"the slowest and most structural of the cycles we track."
        )
    elif cycles:
        upcoming = cycles[0]
        cycle_read = (
            f"Your next major cycle is {upcoming.get('name', 'a return')}, "
            f"{upcoming.get('window', 'ahead')}. These run on decades, not weeks."
        )
    else:
        cycle_read = (
            "No Saturn or Jupiter return falls inside the window we scan. These "
            "cycles run on decades, so gaps are expected."
        )

    cards.append({
        "key": "cycles",
        "name": "Long cycles",
        "source": "Saturn and Jupiter returns",
        "status": "ready",
        "read": cycle_read,
        "more": "timing",
    })

    if retrogrades:
        cards.append({
            "key": "retrogrades",
            "name": "Mercury retrograde",
            "source": "station-to-station periods",
            "status": "ready",
            "read": (
                f"The next period runs {retrogrades[0].get('start')} to "
                f"{retrogrades[0].get('end')}. Traditionally a re-read-the-contract "
                f"window rather than a sign-it one."
            ),
            "more": "timing",
        })

    return cards


# ---------------------------------------------------------------------------
# Timing: today / this week / this month
# ---------------------------------------------------------------------------

# Transit windows run for weeks or months, so bucketing them purely by overlap
# would put the same windows in all three and make the section meaningless.
# Instead the three buckets answer three different questions:
#
#   Today       what is in effect right now
#   This week   what *changes* in the next 7 days -- opens, closes, or goes exact
#   This month  the same, over 31 days
#
# "Changes" is the useful unit: an window that has been running for two months
# is not news, but the day it perfects is.
BUCKETS = (
    ("today", "Today", 0),
    ("week", "This week", 7),
    ("month", "This month", 31),
)


def _changes_within(window: dict, today: dt.date, horizon: dt.date) -> list[dt.date]:
    """Dates on which this window does something, inside the horizon.

    A start date equal to today is not a change: the transit scan clamps
    already-running windows to the start of its range, so half the list would
    otherwise look like it opens this morning. Only a genuinely future opening
    counts.
    """
    moments = []

    start = _as_date(window.get("start"))
    if start and today < start <= horizon:
        moments.append(start)

    end = _as_date(window.get("end"))
    if end and today <= end <= horizon:
        moments.append(end)

    for value in window.get("exact_dates") or []:
        moment = _as_date(value)
        if moment and today <= moment <= horizon:
            moments.append(moment)

    return sorted(set(moments))


def _window_entry(window: dict) -> dict:
    return {
        "title": f"{window.get('transiting')} {window.get('aspect')} {window.get('natal_point')}",
        "dates": f"{window.get('start')} to {window.get('end')}",
        "meaning": window.get("meaning", ""),
        "exact": window.get("exact_dates") or [],
        "perfects": bool(window.get("perfects")),
        "activeNow": bool(window.get("activeNow")),
    }


def _teaser(key: str, count: int, exact_count: int) -> str:
    """What is inside a locked bucket, described without giving it away.

    Every number here is real. A locked box that says nothing reads as an empty
    box, and an invented teaser would be worse than either.
    """
    window_word = "window" if count == 1 else "windows"

    if key == "today":
        if count == 0:
            return "Nothing is crossing your career points today — which is itself worth knowing."
        if exact_count:
            return f"{count} {window_word} in effect, and one goes exact today."
        return f"{count} {window_word} in effect right now."

    period = "this week" if key == "week" else "this month"
    if count == 0:
        return f"Nothing opens, closes or goes exact {period}. Steady ground."

    exact_note = ""
    if exact_count == 1:
        exact_note = " One goes exact, so it has a date on it."
    elif exact_count > 1:
        exact_note = f" {exact_count} go exact, so they have dates on them."

    verb = "shifts" if count == 1 else "shift"
    return f"{count} {window_word} {verb} {period}.{exact_note}"


def timing_buckets(timing: dict, tier: str) -> list[dict]:
    """Group windows into today / this week / this month.

    Free tier receives the shape and an honest teaser; the windows themselves
    are never serialised into the response.
    """
    today = _today()
    windows = timing.get("windows", [])
    buckets = []

    for key, label, horizon_days in BUCKETS:
        horizon = today + dt.timedelta(days=horizon_days)
        matched = []
        exact_count = 0

        for window in windows:
            start = _as_date(window.get("start"))
            end = _as_date(window.get("end"))
            if not start or not end:
                continue

            exact_dates = [d for d in (_as_date(x) for x in window.get("exact_dates") or []) if d]

            if key == "today":
                # In effect now, or perfecting today.
                if start <= today <= end or today in exact_dates:
                    matched.append(window)
                    exact_count += sum(1 for d in exact_dates if d == today)
            else:
                # Something about this window changes inside the horizon.
                changes = _changes_within(window, today, horizon)
                if changes:
                    matched.append(window)
                    exact_count += sum(1 for d in exact_dates if today <= d <= horizon)

        bucket = {
            "key": key,
            "label": label,
            "count": len(matched),
            "exactCount": exact_count,
            "teaser": _teaser(key, len(matched), exact_count),
            "locked": tier == "free",
        }
        if tier != "free":
            bucket["entries"] = [_window_entry(w) for w in matched]
        buckets.append(bucket)

    return buckets


# ---------------------------------------------------------------------------
# Birth-time precision
# ---------------------------------------------------------------------------


def precision(chart: Chart) -> dict:
    """What we can and cannot calculate, and what would change with a time.

    Framed as the upgrade it is rather than as an error. Nothing is broken when
    a birth time is missing -- a specific, nameable layer is simply switched
    off, and saying which one is more persuasive than a warning triangle.
    """
    if chart.birth.time_known:
        return {"exact": True}

    return {
        "exact": False,
        "headline": "Your reading is running without houses",
        "body": (
            "You didn't give an exact birth time, so we've built this from the "
            "parts of your chart that don't need one: sign placements, aspects "
            "and every transit date. Those are calculated exactly as they would "
            "be otherwise."
        ),
        "unlocks": [
            "Your Midheaven — the single most career-specific point in a chart",
            "Which house your Sun, Saturn and Mars actually fall in",
            "The 10th, 6th and 2nd house placements behind how you're read at work",
        ],
        "cta": "Add your birth time",
        "note": (
            "Even an approximate time helps. If you know it within an hour, say "
            "so — we'll tell you which parts stay reliable at that precision."
        ),
    }


# ---------------------------------------------------------------------------
# The whole payload
# ---------------------------------------------------------------------------

# Which reading fields feed which tab. Kept here so the tab structure has one
# definition rather than being reimplemented in the template and the client.
TABS = (
    {"key": "identity", "label": "Who You Are", "field": "core_read", "kind": "prose"},
    {"key": "operating", "label": "How You Operate", "field": "operating_style", "kind": "prose"},
    {"key": "strengths", "label": "Strengths", "field": "strengths", "kind": "items"},
    {"key": "blindspots", "label": "Blind Spots", "field": "friction", "kind": "items"},
)


def build(
    chart: Chart,
    profile: CareerProfile,
    timing: dict,
    content: dict,
    tier: str,
) -> dict:
    """Assemble everything the dashboard renders."""
    archetype = content.get("archetype") or {}
    tabs = []
    for tab in TABS:
        value = content.get(tab["field"])
        if tab["kind"] == "items":
            value = value or []
            if not value:
                continue
        else:
            value = (value or "").strip()
            if not value:
                continue
        tabs.append({**tab, "content": value})

    return {
        "archetype": {
            "name": archetype.get("name") or "Your working signature",
            "line": archetype.get("line") or content.get("headline", ""),
            "signature": content.get("headline", ""),
        },
        "systems": systems(chart, profile, timing),
        "tabs": tabs,
        "timing": timing_buckets(timing, tier),
        # The buckets answer different questions and overlap, so they must not
        # be summed for a headline figure. This is the real count.
        "totalWindows": len(timing.get("windows", [])),
        "horizonMonths": 18,
        "precision": precision(chart),
        "nextStep": content.get("next_step", ""),
        "tier": tier,
    }


__all__ = ["build", "systems", "timing_buckets", "precision", "TABS", "BUCKETS"]
