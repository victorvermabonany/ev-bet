"""The AI interpretation layer.

Structured, already-computed chart data goes in; plain-language career guidance
comes out. This module does no astrology of its own -- it cannot, by design.
Every fact it is allowed to assert is handed to it as a computed placement with
a real number attached, and the schema forces each claim to cite the placement
it came from. That is what keeps the product on the "real data, not vibes" side
of its own positioning.

If no API key is configured, a deterministic template renderer takes over so the
app still returns a genuine chart-derived reading. It is plainly labelled as
such rather than silently pretending to be the AI path.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from dataclasses import dataclass

from .career import CareerProfile
from .chart import Chart

log = logging.getLogger(__name__)

MODEL = os.environ.get("ASTRO_MODEL", "claude-opus-5")
MAX_TOKENS = int(os.environ.get("ASTRO_MAX_TOKENS", "8000"))

# PRD open question 1 (brand voice). Defaulting to "grounded" -- the product is
# positioned on credibility and real calculation, and Co-Star already owns the
# playful/blunt register. Switch to "playful" here to flip the whole tone; it is
# deliberately a one-line change rather than something baked into the prompt.
VOICE = os.environ.get("ASTRO_VOICE", "grounded")

VOICES = {
    "grounded": (
        "Grounded, warm, and specific -- like a sharp mentor who happens to read "
        "charts. Plain sentences. No mysticism, no cosmic throat-clearing, no "
        "em-dash-heavy aphorisms. You are talking to a 26-year-old deciding "
        "whether to take a job, not delivering a prophecy."
    ),
    "playful": (
        "Dry, quick, and a little irreverent, but never cruel and never vague. "
        "Short sentences. The wit is in the precision, not in being cryptic."
    ),
}

SYSTEM_PROMPT = """You write career guidance based on real, pre-calculated astrological data.

## What you are working with

Every placement, aspect, and date in the user message was computed from the \
Swiss Ephemeris for this specific person's birth moment and location. These are \
real astronomical positions, not generated text. Treat them as facts.

## Absolute rules

1. Never invent a placement, aspect, degree, or date. If it is not in the data \
you were given, it does not exist. You have no other information about this person.
2. Every claim you make must trace to a specific placement in the data, and you \
must name that placement in the `evidence` field. "Your Saturn in the 9th house" \
is evidence. "Your energy right now" is not.
3. Never contradict the data. If Mercury is retrograde, do not say it is direct.
4. If the birth time is unknown, the data will say so. In that case you must not \
mention houses, the Midheaven, or the Ascendant at all -- they cannot be known \
without a birth time, and claiming otherwise is the single fastest way to lose a \
user's trust. Work from signs and aspects instead, and say plainly that a birth \
time would sharpen it.
5. A transit window that never goes exact (`perfects: false`) is pressure that \
builds and eases without resolving. Do not describe it as a decisive moment. \
Windows that do go exact have real dates -- use them.

## What makes this useful

This is a *career* product. Stay on: what kind of work fits, how this person \
operates at work, when to move, when to wait, how to approach a negotiation or \
an offer. Do not drift into romance, health, or general personality reading.

Be specific and falsifiable rather than flattering. "You are drawn to work where \
you are the one who fixes what is broken" beats "you have great potential." \
Astrology earns its keep here as a structured lens for thinking about a decision \
the person is already turning over -- write like that is what it is. Never claim \
to predict the future with certainty, and never tell someone that the stars \
require a specific irreversible action. Offer timing as framing, not as command.

## Voice

{voice}

Write in second person. No headers or bullet characters inside field text -- the \
app renders the structure. Aim for two to four sentences per body field."""


READING_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "One sentence, under 90 characters, naming this person's working signature.",
        },
        "core_read": {
            "type": "string",
            "description": "3-5 sentences on the kind of work this chart points to and how they operate in it.",
        },
        "strengths": {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "evidence": {
                        "type": "string",
                        "description": "The exact placement this is drawn from, e.g. 'Saturn 8°00' Aries in the 9th house'.",
                    },
                },
                "required": ["title", "body", "evidence"],
                "additionalProperties": False,
            },
        },
        "friction": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["title", "body", "evidence"],
                "additionalProperties": False,
            },
        },
        "timing": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "window": {"type": "string", "description": "Short name for the window."},
                    "dates": {"type": "string", "description": "The date range, copied from the data."},
                    "guidance": {"type": "string", "description": "What to actually do or avoid in this window."},
                    "evidence": {"type": "string"},
                },
                "required": ["window", "dates", "guidance", "evidence"],
                "additionalProperties": False,
            },
        },
        "next_step": {
            "type": "string",
            "description": "One concrete thing to do in the next 30 days.",
        },
    },
    "required": ["headline", "core_read", "strengths", "friction", "timing", "next_step"],
    "additionalProperties": False,
}


@dataclass
class Reading:
    content: dict
    source: str          # "claude" | "offline"
    model: str | None
    tier: str

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "source": self.source,
            "model": self.model,
            "tier": self.tier,
            "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        }


def api_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def _client():
    import anthropic

    return anthropic.Anthropic()


def build_facts(chart: Chart, profile: CareerProfile, timing: dict, tier: str) -> dict:
    """The exact, bounded set of facts the model is allowed to reason from.

    Free tier gets the natal signature plus the single most relevant active
    window. Paid tier gets the full forward calendar. The cut is here, in the
    data, rather than in the prompt -- a paywall enforced by instruction is one
    jailbreak away from leaking, and this way the free tier physically cannot
    return the paid content.
    """
    windows = timing["windows"]
    cycles = timing["cycles"]

    if tier == "free":
        windows = ([w for w in windows if w["activeNow"]] or windows)[:1]
        cycles = [c for c in cycles if c["status"] == "current"][:1]
    else:
        windows = windows[:8]
        cycles = cycles[:4]

    facts = {
        "birth": chart.birth.to_dict(),
        "birthTimeKnown": chart.birth.time_known,
        "placements": [
            {
                "body": body,
                "position": position.display,
                "sign": position.sign,
                "retrograde": position.retrograde,
                **({"house": chart.placements[body]} if chart.birth.time_known else {}),
            }
            for body, position in chart.positions.items()
        ],
        "careerSignatures": [s.to_dict() for s in profile.signatures],
        "majorAspects": [
            f"{a.body_a} {a.aspect} {a.body_b} (orb {a.orb:.1f}°)"
            for a in chart.aspects[:10]
        ],
        "elements": chart.element_balance(),
        "transitWindows": windows,
        "lifeCycles": cycles,
        "mercuryRetrograde": timing["mercuryRetrograde"][:3],
        "today": dt.date.today().isoformat(),
    }

    if chart.birth.time_known:
        facts["angles"] = {
            "midheaven": profile.midheaven_display,
            "midheavenSign": profile.midheaven_sign,
            "midheavenRuler": profile.midheaven_ruler,
            "midheavenRulerPlacement": profile.midheaven_ruler_placement,
        }
    else:
        facts["note"] = (
            "Birth time is UNKNOWN. Houses, Midheaven and Ascendant are not "
            "available and must not be mentioned."
        )
    return facts


def _tier_instruction(tier: str) -> str:
    if tier == "free":
        return (
            "This is the FREE tier reading. Give a complete, genuinely useful "
            "natal career read: exactly 2 strengths, 1 friction, and 1 timing "
            "entry drawn from the single window provided. Do not allude to "
            "withheld content or advertise the paid tier -- the app handles "
            "that. Just make the free read good on its own terms."
        )
    return (
        "This is the PAID tier reading. Go deeper: 3 strengths, 2-3 frictions, "
        "and 3-4 timing entries that together form a usable calendar. Where two "
        "windows overlap, say what the combination means. Where a window does "
        "not perfect, say so plainly."
    )


def generate(
    chart: Chart,
    profile: CareerProfile,
    timing: dict,
    tier: str = "free",
) -> Reading:
    """Generate a career reading, falling back to templates without a key."""
    facts = build_facts(chart, profile, timing, tier)

    if not api_configured():
        return Reading(offline_reading(chart, profile, timing, tier), "offline", None, tier)

    try:
        content = _generate_with_claude(facts, tier)
        return Reading(content, "claude", MODEL, tier)
    except Exception as exc:  # noqa: BLE001 - a reading must still be returned
        log.warning("Claude generation failed, using offline reading: %s", exc)
        return Reading(offline_reading(chart, profile, timing, tier), "offline", None, tier)


def _generate_with_claude(facts: dict, tier: str) -> dict:
    client = _client()
    system = [
        {
            "type": "text",
            "text": SYSTEM_PROMPT.format(voice=VOICES.get(VOICE, VOICES["grounded"])),
            # The system prompt is identical across every request, so caching it
            # turns the per-reading cost into the chart payload alone.
            "cache_control": {"type": "ephemeral"},
        }
    ]
    user = (
        f"{_tier_instruction(tier)}\n\n"
        "Here is the calculated chart data:\n\n"
        f"```json\n{json.dumps(facts, indent=2)}\n```"
    )

    request = dict(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": READING_SCHEMA},
        },
    )

    message = _stream_with_fallbacks(client, request)

    if message.stop_reason == "refusal":
        raise RuntimeError("model declined to generate this reading")

    text = next((b.text for b in message.content if b.type == "text"), "")
    return json.loads(text)


def _stream_with_fallbacks(client, request: dict):
    """Stream a request, opting into server-side refusal fallbacks.

    Streaming keeps a long generation from tripping the HTTP timeout. The
    `fallbacks` parameter re-runs a policy-declined request on another model
    server-side; if the account does not have that beta enabled we drop it and
    retry plainly rather than failing the user's reading.
    """
    try:
        with client.beta.messages.stream(
            **request,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            return stream.get_final_message()
    except Exception as exc:  # noqa: BLE001
        if "fallback" not in str(exc).lower() and "beta" not in str(exc).lower():
            raise
        log.info("server-side fallbacks unavailable, retrying without: %s", exc)
        with client.messages.stream(**request) as stream:
            return stream.get_final_message()


# ---------------------------------------------------------------------------
# Follow-up questions (paid tier)
# ---------------------------------------------------------------------------

QUESTION_SYSTEM = """You answer one specific career question using this person's \
pre-calculated chart and current transits.

The same rules apply as for a full reading: never invent a placement or a date, \
name the placements you are reasoning from, and if the birth time is unknown do \
not mention houses or angles.

Answer the question that was actually asked. Lead with your read, then the \
reasoning, then the timing if timing is relevant. Four to eight sentences. If \
the question is not about work, say so briefly and redirect -- this product only \
covers career.

Never tell someone the stars require an irreversible decision. You are giving \
them a structured way to think about a choice that is theirs.

Voice: {voice}"""


def answer_question(
    chart: Chart,
    profile: CareerProfile,
    timing: dict,
    question: str,
):
    """Stream an answer to a specific career question.

    Yields text chunks so the UI can render progressively -- these answers are
    the most conversational surface in the product and a spinner would feel
    much worse here than in the one-off reading.
    """
    if not api_configured():
        yield (
            "Live question answering needs an Anthropic API key. Set "
            "ANTHROPIC_API_KEY and restart to enable it. Your chart, timing "
            "windows, and reading above are all real and were calculated "
            "locally -- only this conversational layer is unavailable."
        )
        return

    facts = build_facts(chart, profile, timing, "paid")
    client = _client()

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=2000,
            system=[
                {
                    "type": "text",
                    "text": QUESTION_SYSTEM.format(
                        voice=VOICES.get(VOICE, VOICES["grounded"])
                    ),
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Their question: {question}\n\n"
                        f"Their chart data:\n```json\n{json.dumps(facts, indent=2)}\n```"
                    ),
                }
            ],
            output_config={"effort": "medium"},
        ) as stream:
            for chunk in stream.text_stream:
                yield chunk
            final = stream.get_final_message()
            if final.stop_reason == "refusal":
                yield "\n\n(I can't answer that one. Try rephrasing it as a work question.)"
    except Exception as exc:  # noqa: BLE001
        log.warning("question answering failed: %s", exc)
        yield f"\n\n(Couldn't reach the model just now: {exc})"


# ---------------------------------------------------------------------------
# Offline reading -- real chart data, templated phrasing
# ---------------------------------------------------------------------------

def offline_reading(
    chart: Chart,
    profile: CareerProfile,
    timing: dict,
    tier: str,
) -> dict:
    """A reading assembled from templates over the real computed chart.

    Deliberately plainer than the AI path. It exists so the product degrades to
    "less eloquent" rather than "broken" when no key is configured, and so the
    test suite can exercise the full request path without network access.
    """
    time_known = chart.birth.time_known
    sun = chart.positions["Sun"]
    saturn = chart.positions["Saturn"]
    mars = chart.positions["Mars"]
    mercury = chart.positions["Mercury"]

    if time_known:
        headline = (
            f"{profile.midheaven_sign} Midheaven, {sun.sign} Sun, "
            f"Saturn in {saturn.sign}"
        )
        core = (
            f"Your 10th house cusp sits at {profile.midheaven_display}, so the way "
            f"you are read publicly is coloured by {profile.midheaven_sign}. Its "
            f"ruler, {profile.midheaven_ruler}, is {profile.midheaven_ruler_placement}, "
            f"which is where the substance of that public role actually gets built. "
            f"Your Sun is {profile.sun_placement}, and Saturn -- the slow, "
            f"unglamorous mastery planet -- is {profile.saturn_placement}."
        )
    else:
        headline = f"{sun.sign} Sun, Saturn in {saturn.sign}, Mars in {mars.sign}"
        core = (
            f"Without a birth time the houses and angles can't be calculated, so "
            f"this reads from signs and aspects only. Your Sun is in {sun.sign} "
            f"({sun.display}), Saturn in {saturn.sign}, and Mars in {mars.sign}. "
            f"Adding a birth time would let us place your Midheaven, which is the "
            f"single most career-specific point in a chart."
        )

    strengths = [
        {
            "title": f"Sun in {sun.sign}",
            "body": (
                f"Your core direction runs through {sun.sign}. This is the register "
                f"you are most naturally credible in at work."
            ),
            "evidence": profile.sun_placement if time_known else sun.display,
        },
        {
            "title": f"Mars in {mars.sign}",
            "body": (
                f"How you push, assert, and negotiate. Mars at {mars.display} "
                f"describes the manner that actually works for you when you need "
                f"to ask for something."
            ),
            "evidence": profile.mars_placement if time_known else mars.display,
        },
    ]
    if tier != "free":
        strengths.append({
            "title": f"Mercury in {mercury.sign}",
            "body": (
                f"Your negotiating and contract-reading style. "
                + ("Natally retrograde, so you think it through internally before "
                   "you speak -- give yourself that lag rather than fighting it."
                   if mercury.retrograde else
                   "Direct, so you tend to work things out by saying them aloud.")
            ),
            "evidence": profile.mercury_placement if time_known else mercury.display,
        })

    friction = [{
        "title": f"Saturn in {saturn.sign}",
        "body": (
            f"Saturn marks where progress is slow and earned rather than given. "
            f"At {saturn.display}"
            + (" and retrograde, the authority you are looking for is more likely "
               "to be built internally than granted by someone senior."
               if saturn.retrograde else
               ", this is the area you will be tested in repeatedly until it "
               "becomes a genuine strength.")
        ),
        "evidence": profile.saturn_placement if time_known else saturn.display,
    }]

    missing = [s for s in profile.signatures if s.key == "missing_element"]
    if missing and tier != "free":
        friction.append({
            "title": missing[0].label,
            "body": missing[0].detail,
            "evidence": missing[0].label,
        })

    timing_entries = []
    limit = 1 if tier == "free" else 4
    for window in timing["windows"][:limit]:
        exact = window["exact_dates"]
        if exact:
            guidance = (
                f"Goes exact on {', '.join(exact)}. That is the part of this window "
                f"where decisions tend to actually land."
            )
        else:
            guidance = (
                f"Closes to within {window['peak_orb']}° around {window['peak']} but "
                f"never goes exact, so expect building pressure that eases off "
                f"rather than a single decisive moment."
            )
        timing_entries.append({
            "window": f"{window['transiting']} {window['aspect']} {window['natal_point']}",
            "dates": f"{window['start']} to {window['end']}",
            "guidance": guidance,
            "evidence": window["meaning"],
        })

    if not timing_entries:
        timing_entries.append({
            "window": "No major career transit",
            "dates": "next 18 months",
            "guidance": (
                "No slow-planet contact to your career points in this window. "
                "Quiet stretches are for building, not for forcing a move."
            ),
            "evidence": "computed transit scan returned no windows in range",
        })

    retrogrades = timing["mercuryRetrograde"][:1]
    if retrogrades:
        next_step = (
            f"If you have a contract or an offer in front of you, note that "
            f"Mercury is retrograde {retrogrades[0]['start']} to "
            f"{retrogrades[0]['end']} -- traditionally a re-read-it-twice window "
            f"rather than a sign-it window."
        )
    else:
        next_step = (
            "Write down the single career decision you are actually turning over, "
            "then check it against the timing windows above."
        )

    return {
        "headline": headline,
        "core_read": core,
        "strengths": strengths,
        "friction": friction,
        "timing": timing_entries,
        "next_step": next_step,
    }


__all__ = [
    "Reading", "generate", "answer_question", "build_facts",
    "offline_reading", "api_configured", "MODEL", "VOICE",
]
