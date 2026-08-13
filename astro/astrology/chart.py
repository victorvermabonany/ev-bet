"""Natal chart assembly.

Takes resolved birth data and produces a complete, structured chart. This is
still pure calculation -- every number here traces back to the ephemeris. The
career-specific reading of these numbers lives in ``career.py``, and the
plain-language rendering lives in ``reading.py``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from . import ephemeris as eph
from .places import ResolvedMoment

# Modern rulerships, with the traditional ruler kept alongside. Both matter for
# career work: the traditional ruler of Aquarius (Saturn) says something quite
# different about a person's vocation than the modern one (Uranus), and a good
# reading can hold both.
RULERS = {
    "Aries": ("Mars", "Mars"),
    "Taurus": ("Venus", "Venus"),
    "Gemini": ("Mercury", "Mercury"),
    "Cancer": ("Moon", "Moon"),
    "Leo": ("Sun", "Sun"),
    "Virgo": ("Mercury", "Mercury"),
    "Libra": ("Venus", "Venus"),
    "Scorpio": ("Pluto", "Mars"),
    "Sagittarius": ("Jupiter", "Jupiter"),
    "Capricorn": ("Saturn", "Saturn"),
    "Aquarius": ("Uranus", "Saturn"),
    "Pisces": ("Neptune", "Jupiter"),
}

ELEMENTS = {
    "Aries": "fire", "Leo": "fire", "Sagittarius": "fire",
    "Taurus": "earth", "Virgo": "earth", "Capricorn": "earth",
    "Gemini": "air", "Libra": "air", "Aquarius": "air",
    "Cancer": "water", "Scorpio": "water", "Pisces": "water",
}

MODALITIES = {
    "Aries": "cardinal", "Cancer": "cardinal", "Libra": "cardinal", "Capricorn": "cardinal",
    "Taurus": "fixed", "Leo": "fixed", "Scorpio": "fixed", "Aquarius": "fixed",
    "Gemini": "mutable", "Virgo": "mutable", "Sagittarius": "mutable", "Pisces": "mutable",
}

# What each house means specifically for work. Only the ones a career reading
# has any business touching.
HOUSE_MEANINGS = {
    1: "how you present and are first read by others",
    2: "earned income, pay, and what you consider yourself worth",
    6: "daily work, routine, colleagues, and workload",
    7: "partnerships, clients, negotiation counterparties",
    8: "shared resources, equity, other people's money, salary negotiation",
    10: "career, public role, reputation, and what you are known for",
    11: "networks, professional community, and long-range goals",
}


@dataclass(frozen=True)
class BirthData:
    name: str
    date: dt.date
    time: dt.time
    time_known: bool
    place_label: str
    latitude: float
    longitude: float
    timezone: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "date": self.date.isoformat(),
            "time": self.time.strftime("%H:%M"),
            "timeKnown": self.time_known,
            "place": self.place_label,
            "latitude": round(self.latitude, 4),
            "longitude": round(self.longitude, 4),
            "timezone": self.timezone,
        }


@dataclass
class Chart:
    birth: BirthData
    moment: ResolvedMoment
    julian_day: float
    positions: dict[str, eph.Position]
    houses: eph.Houses
    aspects: list[eph.Aspect]
    placements: dict[str, int] = field(default_factory=dict)

    # -- lookups -----------------------------------------------------------

    def house_of(self, body: str) -> int:
        return self.placements[body]

    def bodies_in_house(self, house: int) -> list[str]:
        return [b for b, h in self.placements.items() if h == house]

    def sign_on_cusp(self, house: int) -> str:
        return eph.sign_of(self.houses.cusp(house))[0]

    def ruler_of_house(self, house: int, traditional: bool = False) -> str:
        sign = self.sign_on_cusp(house)
        return RULERS[sign][1 if traditional else 0]

    def aspects_to(self, body: str) -> list[eph.Aspect]:
        return [a for a in self.aspects if body in (a.body_a, a.body_b)]

    @property
    def age(self) -> float:
        days = (dt.datetime.now(dt.timezone.utc) - self.moment.utc).days
        return days / 365.25

    def element_balance(self) -> dict[str, int]:
        counts = {"fire": 0, "earth": 0, "air": 0, "water": 0}
        for body, position in self.positions.items():
            if body == "North Node":
                continue
            counts[ELEMENTS[position.sign]] += 1
        return counts

    def modality_balance(self) -> dict[str, int]:
        counts = {"cardinal": 0, "fixed": 0, "mutable": 0}
        for body, position in self.positions.items():
            if body == "North Node":
                continue
            counts[MODALITIES[position.sign]] += 1
        return counts

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "birth": self.birth.to_dict(),
            "utc": self.moment.utc.isoformat(),
            "utcOffsetHours": self.moment.utc_offset_hours,
            "dstInEffect": self.moment.dst_in_effect,
            "julianDay": round(self.julian_day, 6),
            "houseSystem": self.houses.system,
            "positions": [
                {**position.to_dict(), "house": self.placements[body]}
                for body, position in self.positions.items()
            ],
            "angles": {
                "ascendant": {
                    "longitude": round(self.houses.ascendant, 4),
                    "display": _format_longitude(self.houses.ascendant),
                },
                "midheaven": {
                    "longitude": round(self.houses.midheaven, 4),
                    "display": _format_longitude(self.houses.midheaven),
                },
            },
            "houses": [
                {
                    "house": i + 1,
                    "longitude": round(cusp, 4),
                    "display": _format_longitude(cusp),
                    "sign": eph.sign_of(cusp)[0],
                }
                for i, cusp in enumerate(self.houses.cusps)
            ],
            "aspects": [a.to_dict() for a in self.aspects],
            "elements": self.element_balance(),
            "modalities": self.modality_balance(),
        }


def _format_longitude(longitude: float) -> str:
    sign, degrees = eph.sign_of(longitude)
    whole = int(degrees)
    minutes = int(round((degrees - whole) * 60))
    if minutes == 60:
        whole, minutes = whole + 1, 0
    return f"{whole}°{minutes:02d}' {sign}"


def build_chart(
    birth: BirthData,
    moment: ResolvedMoment,
    house_system: str = "placidus",
) -> Chart:
    """Compute a full natal chart from resolved birth data."""
    jd = eph.julian_day(moment.utc)
    positions = eph.all_positions(jd)

    # An unknown birth time makes the houses and angles meaningless, since they
    # depend on the exact minute. We compute against a noon chart so sign
    # placements stay usable, and flag it so the reading never claims to know
    # anything house-based. This is the honest handling: the alternative is
    # confidently reporting a Midheaven that is off by up to 180 degrees.
    if not birth.time_known:
        houses = eph.houses(jd, birth.latitude, birth.longitude, "whole_sign")
    else:
        houses = eph.houses(jd, birth.latitude, birth.longitude, house_system)

    placements = {
        body: houses.house_of(position.longitude)
        for body, position in positions.items()
    }
    aspects = eph.find_aspects(positions)

    return Chart(
        birth=birth,
        moment=moment,
        julian_day=jd,
        positions=positions,
        houses=houses,
        aspects=aspects,
        placements=placements,
    )


__all__ = [
    "BirthData", "Chart", "build_chart",
    "RULERS", "ELEMENTS", "MODALITIES", "HOUSE_MEANINGS",
]
