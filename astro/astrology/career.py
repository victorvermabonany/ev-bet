"""Career-relevant extraction and timing.

This is the layer that makes the product a *career* app rather than a general
chart app. It pulls out the placements that traditionally speak to vocation,
work style, and money, and it computes real dated windows from transits.

Everything produced here is structured data with numbers attached. The AI layer
consumes this; it never computes astrology itself. That separation is the whole
point: the chart is calculated, and only the phrasing is generated.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, asdict, field

import swisseph as swe

from . import ephemeris as eph
from .chart import Chart, HOUSE_MEANINGS, RULERS

# The bodies whose transits are slow enough to define a "window" rather than a
# passing mood. Fast movers (Moon, Mercury, Venus) are noise at this timescale.
TRANSIT_BODIES = [
    ("Jupiter", swe.JUPITER),
    ("Saturn", swe.SATURN),
    ("Uranus", swe.URANUS),
    ("Neptune", swe.NEPTUNE),
    ("Pluto", swe.PLUTO),
]

# How much weight each transiting body carries for career questions.
BODY_WEIGHT = {
    "Saturn": 1.00,   # structure, tests, consolidation -- the career planet
    "Jupiter": 0.85,  # opportunity, expansion, offers
    "Pluto": 0.80,    # irreversible restructuring
    "Uranus": 0.75,   # disruption, sudden change, leaving
    "Neptune": 0.55,  # ambiguity, drift, idealism -- weakest for decisions
}

ASPECT_WEIGHT = {
    "conjunction": 1.00,
    "opposition": 0.85,
    "square": 0.85,
    "trine": 0.70,
    "sextile": 0.50,
}

# Which natal points a career transit should be measured against, and why.
CAREER_TARGETS = {
    "Midheaven": "your public career direction and what you're known for",
    "Ascendant": "how you present and the role you step into",
    "Sun": "your core direction and sense of purpose",
    "Saturn": "your relationship to authority, structure, and mastery",
    "Jupiter": "where you find opportunity and room to grow",
    "Mars": "your drive, assertiveness, and willingness to push",
    "Mercury": "how you communicate, negotiate, and handle contracts",
    "Venus": "what you value and how you price yourself",
}


@dataclass
class Signature:
    """A single career-relevant structural fact about the chart."""

    key: str
    label: str
    detail: str
    weight: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TransitWindow:
    """A dated window when a transit is active, with its exact-hit dates."""

    transiting: str
    aspect: str
    natal_point: str
    start: dt.date
    end: dt.date
    exact_dates: list[dt.date]
    peak: dt.date
    peak_orb: float
    score: float
    meaning: str
    retrograde_at_peak: bool

    @property
    def is_active_now(self) -> bool:
        return self.start <= dt.date.today() <= self.end

    @property
    def perfects(self) -> bool:
        """Whether the aspect actually goes exact inside this window.

        A slow planet can enter orb, stall, and retrograde away without ever
        perfecting. That reads very differently -- pressure that builds and
        releases without resolving -- so the interpretation layer needs to be
        able to tell the two apart rather than treating every window as a hit.
        """
        return bool(self.exact_dates)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        d["peak"] = self.peak.isoformat()
        d["exact_dates"] = [x.isoformat() for x in self.exact_dates]
        d["activeNow"] = self.is_active_now
        d["perfects"] = self.perfects
        return d


@dataclass
class MercuryWindow:
    """A Mercury retrograde period -- the classic 'don't sign yet' window."""

    start: dt.date
    end: dt.date

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat()}


@dataclass
class CareerProfile:
    """Everything the interpretation layer is allowed to talk about."""

    midheaven_sign: str
    midheaven_display: str
    midheaven_ruler: str
    midheaven_ruler_placement: str
    tenth_house_bodies: list[str]
    sixth_house_bodies: list[str]
    second_house_bodies: list[str]
    saturn_placement: str
    saturn_aspects: list[str]
    sun_placement: str
    mars_placement: str
    mercury_placement: str
    north_node_placement: str
    signatures: list[Signature] = field(default_factory=list)
    house_time_known: bool = True

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signatures"] = [s.to_dict() for s in self.signatures]
        return d


def _placement(chart: Chart, body: str) -> str:
    """Human-readable placement, house included only when it is actually known.

    Without a birth time the house is an artefact of the noon fallback chart,
    not a fact about the person. Dropping it here means no downstream consumer
    -- prompt, template, or API response -- can accidentally present it as real.
    """
    position = chart.positions[body]
    if not chart.birth.time_known:
        return position.display
    return f"{position.display} in the {_ordinal(chart.placements[body])} house"


def _ordinal(n: int) -> str:
    return {
        1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", 6: "6th",
        7: "7th", 8: "8th", 9: "9th", 10: "10th", 11: "11th", 12: "12th",
    }[n]


def build_profile(chart: Chart) -> CareerProfile:
    """Extract the career-relevant structure of a natal chart."""
    mc_sign = chart.sign_on_cusp(10)
    mc_ruler = chart.ruler_of_house(10)

    # Without a birth time the entire house ring is an artefact of the noon
    # fallback, so every house-derived field has to be blanked -- not just the
    # placement strings. Saturn "in the 10th house" is a claim about the
    # person, and we have no basis for it.
    known = chart.birth.time_known

    profile = CareerProfile(
        midheaven_sign=mc_sign if known else "",
        midheaven_display=_fmt(chart.houses.midheaven) if known else "",
        midheaven_ruler=mc_ruler if known else "",
        midheaven_ruler_placement=_placement(chart, mc_ruler) if known else "",
        tenth_house_bodies=chart.bodies_in_house(10) if known else [],
        sixth_house_bodies=chart.bodies_in_house(6) if known else [],
        second_house_bodies=chart.bodies_in_house(2) if known else [],
        saturn_placement=_placement(chart, "Saturn"),
        saturn_aspects=[
            f"{a.body_a} {a.aspect} {a.body_b} (orb {a.orb:.1f}°)"
            for a in chart.aspects_to("Saturn")
        ],
        sun_placement=_placement(chart, "Sun"),
        mars_placement=_placement(chart, "Mars"),
        mercury_placement=_placement(chart, "Mercury"),
        north_node_placement=_placement(chart, "North Node"),
        house_time_known=chart.birth.time_known,
    )
    profile.signatures = _signatures(chart, profile)
    return profile


def _fmt(longitude: float) -> str:
    sign, degrees = eph.sign_of(longitude)
    whole = int(degrees)
    minutes = int(round((degrees - whole) * 60))
    if minutes == 60:
        whole, minutes = whole + 1, 0
    return f"{whole}°{minutes:02d}' {sign}"


def _signatures(chart: Chart, profile: CareerProfile) -> list[Signature]:
    """The handful of structural facts a career reading should be built on."""
    out: list[Signature] = []

    if chart.birth.time_known:
        out.append(Signature(
            key="midheaven",
            label=f"Midheaven in {profile.midheaven_sign}",
            detail=(
                f"The 10th house cusp -- {HOUSE_MEANINGS[10]} -- sits at "
                f"{profile.midheaven_display}, ruled by {profile.midheaven_ruler}, "
                f"which is {profile.midheaven_ruler_placement}."
            ),
            weight=1.0,
        ))

        if profile.tenth_house_bodies:
            bodies = ", ".join(profile.tenth_house_bodies)
            out.append(Signature(
                key="tenth_house",
                label=f"{bodies} in the 10th house",
                detail=(
                    f"Bodies sitting directly on the career house: {bodies}. "
                    "These describe what is most visible about your working life."
                ),
                weight=0.95,
            ))

        if profile.sixth_house_bodies:
            bodies = ", ".join(profile.sixth_house_bodies)
            out.append(Signature(
                key="sixth_house",
                label=f"{bodies} in the 6th house",
                detail=f"Day-to-day work and routine ({HOUSE_MEANINGS[6]}): {bodies}.",
                weight=0.7,
            ))

        if profile.second_house_bodies:
            bodies = ", ".join(profile.second_house_bodies)
            out.append(Signature(
                key="second_house",
                label=f"{bodies} in the 2nd house",
                detail=f"Earned income and self-worth ({HOUSE_MEANINGS[2]}): {bodies}.",
                weight=0.7,
            ))

    saturn = chart.positions["Saturn"]
    out.append(Signature(
        key="saturn",
        label=f"Saturn in {saturn.sign}",
        detail=(
            f"Saturn -- discipline, authority, and the slow build of mastery -- is "
            f"{profile.saturn_placement}"
            + (" and retrograde, which classically points to authority being "
               "internalised rather than borrowed from others."
               if saturn.retrograde else ".")
        ),
        weight=0.95,
    ))

    sun = chart.positions["Sun"]
    out.append(Signature(
        key="sun",
        label=f"Sun in {sun.sign}",
        detail=f"Core direction and what you are trying to become: {profile.sun_placement}.",
        weight=0.8,
    ))

    mars = chart.positions["Mars"]
    out.append(Signature(
        key="mars",
        label=f"Mars in {mars.sign}",
        detail=(
            f"How you assert, push, and negotiate: {profile.mars_placement}."
        ),
        weight=0.65,
    ))

    mercury = chart.positions["Mercury"]
    out.append(Signature(
        key="mercury",
        label=f"Mercury in {mercury.sign}",
        detail=(
            f"How you communicate and handle contracts: {profile.mercury_placement}"
            + (", natally retrograde -- you tend to process internally before "
               "you speak, and re-reading things twice is not a flaw here."
               if mercury.retrograde else ".")
        ),
        weight=0.6,
    ))

    elements = chart.element_balance()
    dominant = max(elements, key=elements.get)
    if elements[dominant] >= 4:
        out.append(Signature(
            key="element",
            label=f"{dominant.title()}-dominant chart",
            detail=(
                f"{elements[dominant]} of 10 bodies in {dominant} signs "
                f"({', '.join(f'{k} {v}' for k, v in elements.items())})."
            ),
            weight=0.5,
        ))

    missing = [k for k, v in elements.items() if v == 0]
    if missing:
        out.append(Signature(
            key="missing_element",
            label=f"No {', '.join(missing)} placements",
            detail=(
                f"Nothing in {', '.join(missing)} signs -- classically a quality "
                "you build deliberately rather than one that comes for free."
            ),
            weight=0.45,
        ))

    out.sort(key=lambda s: -s.weight)
    return out


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

def _natal_longitude(chart: Chart, point: str) -> float:
    if point == "Midheaven":
        return chart.houses.midheaven
    if point == "Ascendant":
        return chart.houses.ascendant
    return chart.positions[point].longitude


def find_transit_windows(
    chart: Chart,
    start: dt.date | None = None,
    months: int = 18,
    limit: int = 12,
) -> list[TransitWindow]:
    """Find dated career-transit windows over the coming months.

    Scans day by day, so retrograde triple-passes (a transit that goes exact,
    backs off, and returns) surface as multiple exact dates inside one window
    rather than as three unrelated events. That distinction is exactly what
    makes timing advice usable: the first hit is the opening, the last is the
    resolution.
    """
    start = start or dt.date.today()
    end = start + dt.timedelta(days=int(months * 30.44))

    targets = list(CAREER_TARGETS)
    if not chart.birth.time_known:
        targets = [t for t in targets if t not in ("Midheaven", "Ascendant")]

    jd_start = eph.julian_day(
        dt.datetime.combine(start, dt.time(12, 0), tzinfo=dt.timezone.utc)
    )
    total_days = (end - start).days

    # Sample every transiting body once per day up front; the inner loops then
    # run over cached numbers instead of re-entering the ephemeris thousands of
    # times.
    samples = {
        name: [eph.raw(jd_start + d, body_id) for d in range(total_days + 1)]
        for name, body_id in TRANSIT_BODIES
    }

    windows: list[TransitWindow] = []

    for transiting, body_id in TRANSIT_BODIES:
        longitudes = [s[0] for s in samples[transiting]]
        speeds = [s[1] for s in samples[transiting]]
        for target in targets:
            natal = _natal_longitude(chart, target)
            separations = [eph.angular_separation(lon, natal) for lon in longitudes]
            for aspect_name, (angle, base_orb) in eph.ASPECTS.items():
                orb_limit = base_orb * 0.75  # tighter than natal: transits need precision
                offsets = [s - angle for s in separations]
                in_orb = [abs(o) <= orb_limit for o in offsets]
                if not any(in_orb):
                    continue

                # Walk contiguous runs of in-orb days into windows.
                day = 0
                while day <= total_days:
                    if not in_orb[day]:
                        day += 1
                        continue
                    run_start = day
                    while day <= total_days and in_orb[day]:
                        day += 1
                    run_end = day - 1

                    exact_days = _exact_hits(
                        offsets, run_start, run_end, jd_start, natal, angle, body_id
                    )
                    peak_day = min(
                        range(run_start, run_end + 1), key=lambda d: abs(offsets[d])
                    )

                    score = (
                        BODY_WEIGHT[transiting]
                        * ASPECT_WEIGHT[aspect_name]
                        * (1.3 if target in ("Midheaven", "Sun", "Saturn") else 1.0)
                    )

                    windows.append(TransitWindow(
                        transiting=transiting,
                        aspect=aspect_name,
                        natal_point=target,
                        start=start + dt.timedelta(days=run_start),
                        end=start + dt.timedelta(days=run_end),
                        exact_dates=[start + dt.timedelta(days=d) for d in exact_days],
                        peak=start + dt.timedelta(days=peak_day),
                        peak_orb=round(abs(offsets[peak_day]), 3),
                        score=round(score, 3),
                        meaning=(
                            f"transiting {transiting} {aspect_name} your natal "
                            f"{target} -- {CAREER_TARGETS[target]}"
                        ),
                        retrograde_at_peak=speeds[peak_day] < 0,
                    ))

    windows.sort(key=lambda w: (-w.score, w.peak))
    return windows[:limit]


def _exact_hits(
    offsets: list[float],
    run_start: int,
    run_end: int,
    jd_start: float,
    natal: float,
    angle: float,
    body_id: int,
    tolerance: float = 0.02,
) -> list[int]:
    """Days inside a window when the aspect goes exact.

    Exactness cannot be found by looking for a sign change in the offset:
    ``angular_separation`` folds to 0-180, so for a conjunction the offset is
    never negative and for an opposition never positive -- both merely *touch*
    zero. So we look for local minima of |offset| instead, which is correct for
    every aspect type, then refine each candidate against the ephemeris.

    A retrograde planet can cross the same degree three times, and each of
    those passes is a separate local minimum, which is precisely the structure
    that makes timing advice usable.
    """
    hits: list[int] = []
    for day in range(run_start, run_end + 1):
        here = abs(offsets[day])
        before = abs(offsets[day - 1]) if day > run_start else float("inf")
        after = abs(offsets[day + 1]) if day < run_end else float("inf")
        if here > before or here > after:
            continue

        # Refine within +/- one day; daily sampling can miss the true minimum.
        lo, hi = day - 1.0, day + 1.0
        for _ in range(40):
            m1 = lo + (hi - lo) / 3
            m2 = hi - (hi - lo) / 3
            f1 = abs(eph.angular_separation(eph.raw(jd_start + m1, body_id)[0], natal) - angle)
            f2 = abs(eph.angular_separation(eph.raw(jd_start + m2, body_id)[0], natal) - angle)
            if f1 < f2:
                hi = m2
            else:
                lo = m1
        best = (lo + hi) / 2
        residual = abs(
            eph.angular_separation(eph.raw(jd_start + best, body_id)[0], natal) - angle
        )
        if residual <= tolerance:
            hits.append(int(round(best)))
    return sorted(set(hits))


def mercury_retrograde_windows(
    start: dt.date | None = None,
    months: int = 12,
) -> list[MercuryWindow]:
    """Mercury retrograde periods ahead -- directly actionable for contracts."""
    start = start or dt.date.today()
    days = int(months * 30.44)
    jd = eph.julian_day(
        dt.datetime.combine(start, dt.time(12, 0), tzinfo=dt.timezone.utc)
    )

    flags = [
        eph.position(jd + d, "Mercury", swe.MERCURY).retrograde
        for d in range(days + 1)
    ]

    windows: list[MercuryWindow] = []
    day = 0
    while day <= days:
        if not flags[day]:
            day += 1
            continue
        run_start = day
        while day <= days and flags[day]:
            day += 1
        windows.append(MercuryWindow(
            start=start + dt.timedelta(days=run_start),
            end=start + dt.timedelta(days=day - 1),
        ))
    return windows


@dataclass
class LifeCycle:
    """A named, age-anchored career cycle with real dates."""

    name: str
    description: str
    start: dt.date
    end: dt.date
    status: str  # "past" | "current" | "upcoming"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat()
        return d


def life_cycles(chart: Chart) -> list[LifeCycle]:
    """Saturn and Jupiter returns -- the load-bearing career cycles.

    Computed from the actual ephemeris rather than from average orbital
    periods, because Saturn's return can land anywhere in a roughly two-year
    span depending on where it sits natally.
    """
    today = dt.date.today()
    cycles: list[LifeCycle] = []

    natal_saturn = chart.positions["Saturn"].longitude
    natal_jupiter = chart.positions["Jupiter"].longitude

    def find_returns(natal_longitude: float, body_id: int, period_years: float,
                     count: int) -> list[list[dt.date]]:
        """Return events, each as the list of passes belonging to it.

        A retrograde planet crosses its own natal degree up to three times in
        a single return -- forward, back, and forward again. Those are one
        life event, not three, so passes within a year of each other are
        grouped. Reporting them separately would tell a 29-year-old they were
        having three Saturn returns in eighteen months.

        Searching only near each expected return (rather than scanning a whole
        lifetime day by day) keeps this fast enough for a web request.
        """
        jd0 = chart.julian_day
        events: list[list[dt.date]] = []

        for n in range(1, count + 1):
            centre = jd0 + n * period_years * 365.25
            lo_bound = centre - 400
            hi_bound = centre + 400
            step = 3.0
            passes: list[dt.date] = []

            previous_delta = None
            jd = lo_bound
            while jd <= hi_bound:
                longitude = eph.raw(jd, body_id)[0]
                delta = ((longitude - natal_longitude + 180.0) % 360.0) - 180.0
                if previous_delta is not None and abs(delta - previous_delta) < 90:
                    if (previous_delta < 0 <= delta) or (previous_delta > 0 >= delta):
                        lo, hi = jd - step, jd
                        for _ in range(45):
                            mid = (lo + hi) / 2
                            d = ((eph.raw(mid, body_id)[0]
                                  - natal_longitude + 180.0) % 360.0) - 180.0
                            if (d < 0) == (previous_delta < 0):
                                lo = mid
                            else:
                                hi = mid
                        passes.append(eph.jd_to_datetime((lo + hi) / 2).date())
                previous_delta = delta
                jd += step

            if passes:
                events.append(sorted(set(passes)))
        return events

    saturn_events = find_returns(natal_saturn, swe.SATURN, 29.457, count=3)
    for index, passes in enumerate(saturn_events, start=1):
        window_start = passes[0] - dt.timedelta(days=180)
        window_end = passes[-1] + dt.timedelta(days=180)
        exact = ", ".join(p.isoformat() for p in passes)
        cycles.append(LifeCycle(
            name=f"Saturn return #{index}",
            description=(
                "Saturn comes back to where it sat at your birth"
                + (f", crossing that degree {len(passes)} times ({exact}) "
                   "because it retrogrades back over it" if len(passes) > 1
                   else f" (exact {exact})")
                + ". Classically the period when a career built on someone "
                "else's terms gets rebuilt on your own -- it tends to bring "
                "restructuring rather than gentle growth, and what survives it "
                "usually lasts."
            ),
            start=window_start,
            end=window_end,
            status=_status(window_start, window_end, today),
        ))

    # Only look at the Jupiter returns bracketing the present; scanning every
    # return since birth costs time nobody is asking for.
    age_years = max(0.0, (today - chart.moment.utc.date()).days / 365.25)
    first = max(1, int(age_years / 11.862))
    jupiter_events = [
        passes
        for n in (first, first + 1, first + 2)
        for passes in find_returns(natal_jupiter, swe.JUPITER, 11.862, count=n)[n - 1:n]
    ]
    upcoming = [
        passes for passes in jupiter_events
        if passes[-1] >= today - dt.timedelta(days=180)
    ]
    for passes in upcoming[:2]:
        window_start = passes[0] - dt.timedelta(days=90)
        window_end = passes[-1] + dt.timedelta(days=90)
        cycles.append(LifeCycle(
            name="Jupiter return",
            description=(
                f"Jupiter returns to its natal degree (exact "
                f"{', '.join(p.isoformat() for p in passes)}), roughly every 12 "
                "years. Traditionally an opening rather than a test -- the window "
                "where asking for more tends to land better than usual."
            ),
            start=window_start,
            end=window_end,
            status=_status(window_start, window_end, today),
        ))

    cycles.sort(key=lambda c: c.start)
    return cycles


def _status(start: dt.date, end: dt.date, today: dt.date) -> str:
    if end < today:
        return "past"
    if start > today:
        return "upcoming"
    return "current"


def timing_summary(chart: Chart, months: int = 18) -> dict:
    """The complete timing payload: windows, retrogrades, and cycles."""
    windows = find_transit_windows(chart, months=months)
    return {
        "windows": [w.to_dict() for w in windows],
        "mercuryRetrograde": [m.to_dict() for m in mercury_retrograde_windows()],
        "cycles": [c.to_dict() for c in life_cycles(chart)],
        "activeNow": [w.to_dict() for w in windows if w.is_active_now],
    }


__all__ = [
    "CareerProfile", "Signature", "TransitWindow", "MercuryWindow", "LifeCycle",
    "build_profile", "find_transit_windows", "mercury_retrograde_windows",
    "life_cycles", "timing_summary", "CAREER_TARGETS",
]
