# Transit — know when to move

**Your chart. Your timing. Real data, not vibes.**

A career-focused astrology app. It computes a real birth chart from the Swiss
Ephemeris, extracts the placements that traditionally speak to work, finds the
transit windows currently moving across them, and turns that structured data
into specific career guidance with dates attached.

It lives in `astro/` and is completely independent of the EV-betting app at the
repository root — separate entry point, separate dependencies, separate port.

## Why it is built this way

The PRD calls the astronomical layer the highest-risk component and asks for it
to be verified before any interpretation is layered on top. That ordering is
reflected in the code and in the tests:

```
places.py     city -> coordinates -> historical timezone -> UTC
ephemeris.py  UTC -> planetary positions, houses, aspects   (pure astronomy)
chart.py      -> assembled natal chart
career.py     -> career-relevant structure + dated transit windows
reading.py    -> plain-language guidance                    (the only AI step)
```

Interpretation only ever consumes computed numbers. It never calculates
astrology itself, and the response schema forces every claim to cite the
placement it came from — that is what keeps the product on the "real data"
side of its own marketing.

## Verified accuracy

`tests/test_ephemeris_accuracy.py` checks the engine against **external**
references rather than its own output. Measured deviations:

| Check | Reference | Result |
|---|---|---|
| Sun at equinoxes/solstices | 6 published ingress times, 2000–2025 | within **1.2 arcseconds** |
| Sun + Moon at solar eclipses | 4 published eclipses, 1999–2026 | conjunct to **2–5 arcminutes** |
| Eclipse time search | NASA greatest-eclipse instants | within **2–67 seconds** |
| Ascendant / Midheaven | independent spherical-trig derivation | agree to **< 0.0001 arcsec** |
| Mercury retrograde | published 2024 station dates | all periods correct |

The angles matter most: the Midheaven *is* the career point, so the whole
product rests on it. It is re-derived from sidereal time and obliquity and
compared against the Swiss Ephemeris house routine — two independent
derivations agreeing to sub-milliarcsecond.

Positions come from the Moshier analytical ephemeris, which is bundled with
`pyswisseph` and needs no data files. Accuracy is well under an arcminute for
any modern birth date — far finer than astrology's own conventional orbs.

## Running it

```bash
pip install -r astro/requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...     # optional; see below
python astro/app.py                     # http://localhost:5001
```

Tests (no network or API key required):

```bash
python -m pytest astro/tests -v
```

### Without an API key

The app still works. Chart calculation, transit windows, Saturn returns and
Mercury retrograde dates are all computed locally and are exact; only the
prose falls back to a built-in template renderer. The UI labels this plainly
rather than passing templated text off as a full reading.

## Design decisions worth knowing

**Unknown birth times are handled honestly.** Houses and angles depend on the
exact minute — an hour of error moves the Ascendant about 15°, usually a whole
sign. When the birth time is unknown, every house-derived value is blanked at
the source, so no layer downstream can present a noon-fallback artefact as a
fact. The reading works from signs and aspects and says why it is less precise.
Three separate tests enforce this.

**The paywall is enforced in the data, not the prompt.** `build_facts()` gives
the free tier one transit window and the paid tier eight. A tier boundary that
exists only as an instruction is one jailbreak away from leaking; this way the
free tier physically cannot return paid content.

**Retrograde passes are grouped into one event.** Saturn crosses its natal
degree up to three times in a single return. Reported separately, that would
tell a 29-year-old they were having three Saturn returns in eighteen months.

**Windows that never go exact are labelled as such.** A slow planet can enter
orb, stall, and retrograde away without perfecting — real pressure, but not a
decisive moment. The UI tags these "never exact" instead of implying a hit.

**Nothing is stored.** No database and no accounts; the browser holds the birth
data and posts it per request. Charts are cached in memory for the process
lifetime only.

## Deploying

The repository root's `Procfile` belongs to the EV-betting app and is left
alone. To deploy this app instead, point the service at `astro/` and run:

```
gunicorn --chdir astro app:app --timeout 120 --workers 2
```

`--timeout 120` matters: the question endpoint streams, and the transit scan
takes about half a second of CPU on a cold chart.

## The landing page

`/` opens on a landing page built to the landing PRD; the chart form is step two,
reached only by the CTA.

- **Minimal nav** — wordmark, two links (one dropdown), one CTA. Below 860px it
  collapses to wordmark + CTA; the dropdown targets all live on the landing
  page, so nothing becomes unreachable.
- **Trust badge** — "Positions from the Swiss Ephemeris — real astronomical
  data". Deliberately a claim about the calculation engine, which is real and
  checkable, rather than a user count we would have to invent. The PRD is right
  that a fabricated stat would undercut the exact mechanic it's borrowing.
- **Two-clause headline** — "Know when to move." (feeling) / "Real data, not
  vibes." (capability), the second clause in gold italic.
- **One CTA, repeated** — "Get your chart" in the nav, the hero, and the closing
  section. All three do the same thing. There is no competing secondary button
  anywhere on the page.
- **Mood before claim** — a full-bleed night sky that warms into the page cream.
  It's a generated canvas starfield, not stock imagery: nothing to ship, it
  scales to any viewport, and it's the sky the charts are calculated from. It
  goes still under `prefers-reduced-motion` and pauses when the tab is hidden.
- **No logo wall.** The PRD says to leave it out until the numbers are real, so
  the section does not exist. Add it when there is something true to put in it.
- **No urgency tactics** — no countdowns, no scarcity. They'd contradict the
  calm, credible register the rest of the product works in.

## Consistency rules across screens

The landing page's principles are applied to every screen, not just the
marketing page. There are four, and they are enforced by an in-browser audit
rather than by eye.

**One heading system.** Every screen leads with an eyebrow and a two-clause
serif headline: benefit first, the specific/capability clause second and in the
accent.

| Screen | Benefit clause | Specific clause |
|---|---|---|
| Landing | Know when to move. | Real data, not vibes. |
| Intake | Four fields, one real chart. | Calculated, not guessed. |
| Loading | Calculating your chart. | — |
| Results | Your chart, decoded. | *the generated signature* |

On the results screen the generated headline becomes the second clause, so the
personal payoff keeps the accent treatment the landing gives its capability
line.

**One primary CTA per screen.** The audit found three violations and all three
are fixed: the nav CTA used to render on every screen (competing with
"Calculate my chart" on the intake and "Unlock" on the results), so it is now
gated to the marketing page; "Start over" was a second button and is now a
quiet text link. Chips in the ask box are input affordances, not calls to
action, and stay.

**One typography system.** Serif headings, sans body, mono for anything
calculated — everywhere, not just the landing. Two things changed to hold the
line: dates inside status tags now take the mono face while the status word
stays sans, and the reading's opening paragraph moved from serif to sans. It is
generated prose rather than a heading, and the landing page has no serif body
text either, so it was the one place the app disagreed with itself.

**Imagery stays on the marketing page.** The full-bleed night sky, the
starfield and the trust badge exist only on the landing view — dense imagery
behind a form or a dense results table would cost readability for nothing. App
screens use the cream/terracotta palette throughout. The nav follows the same
rule: inverted while it is genuinely over the dark hero, cream everywhere else,
including once you scroll past the sky on the landing page itself.

## The mark

A chart wheel, its horizon (the Ascendant–Descendant axis), and a body crossing
the top of the wheel — the Midheaven, which is the career point. Four primitives,
and between them they state what the product does. Geometric rather than an
ornate zodiac wheel, and it reappears as the favicon, the step icons, the
loading spinner, and the faint arc behind the paywall.

## Design system

Built to the brand kit. The five palette values are exact; everything else is
derived from them.

| Role | Token | Hex |
|---|---|---|
| Background | `--cream` | `#F7F1E8` |
| Primary text | `--ink` | `#2B2620` |
| Accent, primary | `--terracotta` | `#C1592B` |
| Accent, secondary | `--navy` | `#1F2A44` |
| Highlight / success | `--gold` | `#C9A24B` |

Neutrals (`--ink-soft`, `--sand`, `--card`…) are warm-biased toward the cream
rather than flat greys, so they read as chosen rather than inherited.

**Three typefaces, one job each** — and the split is the brand argument:

| Face | Token | Used for |
|---|---|---|
| Fraunces | `--serif` | Headlines and the lede |
| Inter | `--sans` | Body copy, labels, UI |
| Space Mono | `--mono` | Every calculated value |

Anything the ephemeris produced — degrees, dates, coordinates, Julian day — is
set in Space Mono with tabular figures. Anything written is set in Inter. You
can tell computed data from interpretation at a glance, which is the product's
whole positioning rendered as typography.

**Colour encodes meaning, it isn't decoration.** In the timing section,
terracotta means the window is live now, gold means the aspect goes exact on a
real date, and muted sand means it enters orb but never perfects. Navy carries
the night-sky surfaces: the paywall panel, the Midheaven/Ascendant readouts,
and the friction rail.

Fonts are self-hosted in `static/fonts/` (~330 KB, latin + latin-ext subsets)
rather than loaded from a CDN. The chart engine already runs offline, and a
webfont that silently falls back would undo half the identity.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/places?q=` | Offline city search (34k cities) |
| `POST /api/chart` | Full chart, career profile, timing |
| `POST /api/reading` | Generated reading (`tier`: `free` \| `paid`) |
| `POST /api/question` | Streaming answer to one career question (SSE) |
| `GET /health`, `/api/config` | Status |

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Enables the AI reading layer |
| `ASTRO_MODEL` | `claude-opus-5` | Model |
| `ASTRO_VOICE` | `grounded` | Brand voice — `grounded` or `playful` |
| `ASTRO_PRICE_LABEL` | `$5.99/mo` | Paywall copy |
| `PORT` | `5001` | Server port |

## Where the PRD's open questions landed

1. **Brand voice** — defaulted to **grounded**. The product is positioned on
   credibility, and Co-Star already owns the playful register. It is a
   one-variable change (`ASTRO_VOICE=playful`), so it can be A/B tested rather
   than argued about.
2. **Q&A in v1 or v2** — **shipped in v1**, gated to the paid tier. The chart
   and transit infrastructure it needs already existed, so the marginal cost
   was one endpoint, and "should I take this offer?" is the single most
   career-specific thing the app can answer.
3. **Pricing** — left as configuration. Not a code decision.

## Not built (explicit v1 non-goals)

Relationship compatibility, general daily horoscopes, live astrologer consults,
and birth-chart education — all excluded per the PRD.

Payments are stubbed: the "unlock" button flips the tier client-side and calls
the paid endpoint. Wiring a real processor is the next step, and the tier split
already runs through a single server-side parameter.
