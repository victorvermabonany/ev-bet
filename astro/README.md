# Northstar — know when to move

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

## Running it locally

From the repository root, on the `claude/career-astrology-app-sgt5t7` branch:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r astro/requirements.txt
python astro/app.py
```

Open **http://localhost:5001** and enter any birth date you like. Charts are
calculated live by the Swiss Ephemeris — there is nothing precomputed in the
running app.

Optional, for the AI-written reading:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # before python astro/app.py
```

Verified from an empty virtualenv against this exact `requirements.txt`, so
nothing is missing. Notes:

- **Python 3.10+.** Built and tested on 3.11.
- **First request takes ~3s.** The city index and timezone dataset warm on
  first use; every chart after that is ~0.5s.
- **Port** is 5001 by default; `PORT=8080 python astro/app.py` to change it.
- Anything that isn't a real city gets a "pick one from the list" error — the
  place field needs a selection from the dropdown so it has coordinates and a
  timezone.

Tests (no network or API key needed):

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

## Deploying to Render

`render.yaml` at the repository root defines this app as its own service. It
does **not** touch the existing ev-bet service — that one was created manually
in the dashboard and keeps using the root `Procfile`. A blueprint only affects
services you explicitly create from it, so the two run side by side off the
same repo.

Dashboard → **New** → **Blueprint** → pick this repo and the
`claude/career-astrology-app-sgt5t7` branch → **Apply**. Then set
`ANTHROPIC_API_KEY` on the service if you want the AI reading; without it every
chart is still calculated and the built-in template reader writes the prose.

Two settings in there are deliberate and worth keeping:

- **One worker, four threads.** The process sits at ~180 MB resident once the
  city index and timezone dataset are warm. Two workers would be ~360 MB and
  risk the OOM killer on the 512 MB free plan. Threads give concurrency
  instead; a chart is ~0.5s of CPU and the ephemeris calls serialise behind a
  lock anyway.
- **`--timeout 120`.** The question endpoint streams, and a cold chart request
  does real work.

On the free plan the service sleeps when idle, so the first request after a
nap pays both the container cold start and the ~3s dataset warm-up.

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

## The live sky

The hero carries a readout of the actual current sky, computed at page render
from the same Swiss Ephemeris the charts use — today's Moon phase and sign,
Mercury's retrograde status, and the closest aspect currently held.

It is there as evidence rather than decoration. The badge above it claims "real
astronomical data", and the cheapest way to support that claim is to show some
and let anyone check it against their own ephemeris.

Three decisions worth keeping:

- **The Moon graphic is drawn from the illumination figure**, not chosen from a
  set of eight phase images. The terminator is an ellipse of semi-minor axis
  `r·|1−2k|`, so the disc on screen *is* the number. Verified against published
  new and full moon instants for 2024–2026, where elongation lands on 0° and
  180° to under a degree.
- **The reported aspect must involve a body that actually moves.** The tightest
  aspect in the sky is almost always between two outer planets — Neptune
  sextile Pluto sits inside a degree for years. Real, but presenting it as what
  is happening *right now* would leave the line unchanged for months, so at
  least one body must come from Sun through Jupiter.
- **Nothing is invented when data is missing.** If no aspect is within orb the
  line says so, because an unusually quiet sky is itself true and interesting.

`test_sky.py` checks the phase maths against published lunation times and
Mercury's status against published retrograde periods, and asserts the payload
contains no social proof of any kind.

Glyphs are pinned to text presentation with U+FE0E. Without it browsers render
♌ and ♀ as colour emoji, which fights the typography around them.

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

## The dashboard

The screen a user lands on once their chart is calculated. The full chart detail
still exists, one click away behind **View full chart** — the dashboard is a
summary, not a dump.

| Section | What it does |
|---|---|
| Archetype | A two-to-four word working signature (`The Analytical Builder`) plus one grounded line. Generated by the AI when a key is set; derived deterministically from the element and modality of the career-defining sign otherwise |
| What we read | One card per layer of chart data we genuinely compute, each with a real read and a "read more" |
| Your reading | Four tabs — Who You Are / How You Operate / Strengths / Blind Spots — mapped from `core_read`, `operating_style`, `strengths` and `friction` |
| Timing | Today / This week / This month. Locked for free users, with a real teaser rather than a blank box |
| Do this next | The single concrete action from the reading |

**On "systems".** The dashboard shows the layers behind the reading — natal
placements, houses and angles, current transits, long cycles, Mercury retrograde
— and stops there. It does not claim a numerology, Human Design or Enneagram
engine, because there isn't one. The product reads one tradition through several
genuinely distinct layers, and those layers differ in a way worth showing: houses
need an exact birth time and the others do not. `test_dashboard.py` asserts the
absence of the invented ones, so it stays true.

**The three timing buckets answer three different questions.** Transit windows
run for weeks or months, so bucketing purely by overlap put the same windows in
all three and made the section meaningless. Today is what is *in effect*; this
week and this month are what *changes* — opens, closes, or goes exact. A start
date equal to today is ignored, because the scan clamps already-running windows
to the start of its range and half the list would otherwise look like it opened
this morning.

**No birth time is an offer, not an error.** The house layer reads as switched
off, with the three things a time would unlock and a plain statement that
everything else is calculated exactly as it would be otherwise. The tests check
the copy for scolding words (`error`, `required`, `invalid`, `failed`) so it
cannot drift back into a validation warning.

**Chat with your chart** is not built — it was scoped as v2. When it is, the
transparent usage quota belongs in the dashboard header, and the server-side
counter it should read from already exists in `astrology/ratelimit.py`.

## API

| Endpoint | Purpose |
|---|---|
| `GET /api/places?q=` | Offline city search (34k cities) |
| `POST /api/chart` | Full chart, career profile, timing |
| `POST /api/reading` | Generated reading — tier decided **server-side**, never by the caller |
| `POST /api/dashboard` | The dashboard payload; shares the reading cache so it costs no extra generation |
| `POST /api/question` | Streaming answer to one career question (SSE); `402` without a membership |
| `GET /api/entitlement` | What this session may see — the UI's only source of truth |
| `POST /api/checkout` | Creates a Whop checkout configuration carrying this session's token |
| `POST /api/whop/webhook` | Signed membership events from Whop; the only thing that grants access |
| `GET /api/sky` | Today's sky — the payload the landing page renders from |
| `GET /health`, `/api/config` | Status |

## Pricing and checkout (Whop)

Two plans, created with the Whop CLI by `scripts/setup_whop.sh`:

| | Plan | Price | Trial | Treatment |
|---|---|---|---|---|
| Default | Weekly | **$7.99** / week | **3 days free** | Highlighted — terracotta border, gold "3 days free" badge, pre-selected, and the CTA reads "Start free trial" |
| Secondary | Annual | $89 / year | — | Present and legible, but no accent, no badge, no border weight |

```bash
curl -fsSL https://whop.com/install.sh | sh   # if you don't have the CLI
whop login                                    # or: export WHOP_API_KEY=whop_xxx
sh astro/scripts/setup_whop.sh                # prints the plan IDs
```

Then set what it prints (`WHOP_PRODUCT_ID`, `WHOP_WEEKLY_PLAN_ID`,
`WHOP_ANNUAL_PLAN_ID`) and restart. The app reads them from `/api/config`.

**Where the paywall sits.** Exactly at the transition the free reading stops
at. The locked sections continue behind a blur that fades into the page ground,
with the pricing card sitting over that boundary — so you can see there is more
rather than hitting a wall.

The blurred shapes are **skeletons generated in the browser**. No paid content
is sent to the client and then hidden with CSS; the tier split stays enforced
server-side in `build_facts()`, which is the only place it can't be undone with
devtools.

**The checkout modal** is Whop's embedded overlay
(`js.whop.com/static/checkout/loader.js`). Clicking the CTA appends an element
carrying `data-whop-checkout-session` and `data-whop-checkout-overlay`; the
loader runs a MutationObserver, so an element added at click time mounts and
opens. The `postMessage` that arrives on completion only makes the UI re-ask
the server — it cannot itself unlock anything.

It has to be `data-whop-checkout-session` rather than the simpler
`data-whop-checkout-plan-id`, and that constraint shaped the design below: the
embed has **no metadata attribute** (reading the shipped `index.js`, the only
`data-*` hooks it reads are `plan-id`, `session`, `overlay` and `style-*`). A
server-created *checkout configuration* is the one thing that can carry
metadata into a purchase — hence `POST /api/checkout` and `whop_api.py`.

## How the paywall is actually enforced

The tier a caller receives is derived entirely on the server. `POST
/api/reading` **ignores any `tier` in the request body**; it reads the session
cookie, looks up a membership recorded by a signed webhook, and returns
whatever that session has genuinely paid for.

### Identity: an anonymous session token

No email, no password, no account. First request mints a random token stored in
an httpOnly, SameSite=Lax cookie (`transit_sid`), and a `(session_id,
membership_id)` row is what "being a subscriber" means.

Whop already authenticates the buyer, so an email or magic-link signup would
rebuild an identity system we get for free and create two sources of truth
about who paid. Magic links also need an email-sending dependency, and an email
gate before checkout adds friction at the worst possible moment. The
session→membership table is the same table we would keep if Whop OAuth or magic
links were added later, so this is a foundation rather than a detour.

**The known gap:** clearing cookies, or switching browser or device, loses
access until there is a restore flow. Whop OAuth ("log in with Whop") is the
natural fix and re-uses the same table — it just adds a second way to arrive at
a `session_id`. Worth building before this takes real money from real people.

### The flow

```
GET /            -> mints transit_sid, httpOnly cookie
POST /api/checkout   -> Whop checkout configuration with metadata {"sid": …}
   (user pays on Whop's overlay)
POST /api/whop/webhook  <- membership.went_valid, HMAC-signed
                        -> row: (sid, membership_id, status, valid_until)
POST /api/reading    -> looks up sid, returns paid tier
```

### What is deliberately strict

- **The webhook fails closed.** With no `WHOP_WEBHOOK_SECRET` set it rejects
  everything. An unauthenticated endpoint that grants paid access would be a
  worse hole than the client-side flag it replaces, because nobody would ever
  see it being used.
- **Signatures are compared with `hmac.compare_digest`** over the raw body,
  before any parsing.
- **`trialing` counts as entitled.** Gating on `active` alone would lock out
  every 3-day-trial user — exactly the audience the highlighted plan targets.
- **Expiry is enforced independently of webhooks.** `valid_until` is checked on
  every read, so a webhook Whop never successfully delivers cannot leave access
  switched on forever.
- **No paid content reaches the client and gets hidden with CSS.** The tier cut
  happens in `build_facts()` before generation: free tier receives 1 transit
  window, paid receives up to 8. The blurred shapes in the locked sections are
  skeletons generated in the browser.

### Verifying it

`tests/test_entitlements.py` covers this in-process (31 tests). To prove it
against a running server end to end:

```bash
ASTRO_DB_PATH=/tmp/live.db WHOP_WEBHOOK_SECRET=live-secret-abc python app.py &
sh scripts/verify_paywall.sh
```

18 checks, all passing as of this commit — unauthenticated `tier: "paid"` comes
back free; a wrongly-signed webhook is rejected with `401` and grants nothing;
a correctly-signed one flips that one session to paid; a different session and
a guessed token both stay free; and a `went_invalid` event revokes access.

### Before this handles real money

The grants table is SQLite at `ASTRO_DB_PATH`. **Render's free plan has an
ephemeral filesystem**, so it is wiped on every deploy and restart — paying
customers would silently lose access. Attach a persistent disk, or point the
app at managed Postgres, before launch.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Enables the AI reading layer |
| `ASTRO_MODEL` | `claude-opus-5` | Model |
| `ASTRO_VOICE` | `grounded` | Brand voice — `grounded` or `playful` |
| `WHOP_WEEKLY_PLAN_ID` | — | Weekly plan (`plan_…`) from the setup script |
| `WHOP_ANNUAL_PLAN_ID` | — | Annual plan (`plan_…`) |
| `WHOP_PRODUCT_ID` | — | Product the plans hang off |
| `WHOP_WEEKLY_PRICE` / `WHOP_ANNUAL_PRICE` | `$7.99` / `$89` | Display copy only |
| `WHOP_TRIAL_DAYS` | `3` | Trial length shown on the badge |
| `WHOP_API_KEY` | — | **Required for real checkout** — creates the checkout configuration that carries the session token |
| `WHOP_WEBHOOK_SECRET` | — | **Required to grant access** — HMAC secret for `/api/whop/webhook`. Unset means every webhook is rejected |
| `ASTRO_DB_PATH` | `entitlements.db` | SQLite file holding membership grants. Must be on a persistent disk in production |
| `PORT` | `5001` | Server port |

Point Whop's webhook at `https://<your-host>/api/whop/webhook` and subscribe to
the membership events (`membership.went_valid`, `membership.went_invalid`).
Copy the signing secret it gives you into `WHOP_WEBHOOK_SECRET`.

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
