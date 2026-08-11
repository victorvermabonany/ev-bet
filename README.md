# Ember

Small-group lunches in your NYC neighborhood. People sign up with their area
and the times they're free; the matcher seats them in tables of three or four.

`Ember` is a placeholder name — it lives in `src/config.js` alongside the
tagline, so changing it there updates every screen that shows the wordmark.
The page `<title>` and the favicon's `aria-label` are the only other spots.

## Running it

```bash
npm install
npm run dev      # client on :5173, API on :3001
```

`npm run dev` starts both processes. Vite proxies `/api` to the API, so the
client always talks to same-origin paths and there's no CORS setup.

| Command | What it does |
| --- | --- |
| `npm run dev` | client + API together, both watching |
| `npm run build` | production client bundle → `dist/` |
| `npm start` | API only; also serves `dist/` once built |
| `npm run seed` | replace stored signups with 14 fake ones |
| `npm run match` | print the current groups to the console |
| `npm test` | matching logic unit tests |

## Screens

| Route | What it is |
| --- | --- |
| `/` | homepage — wordmark and Get Started |
| `/signup` | the signup form |
| `/welcome` | confirmation, shown after signing up |
| `/admin` | the matched groups |

## Storage

Signups are appended to `data/signups.json` — a plain JSON file, which is the
fastest thing to stand up and the easiest to read by hand. `data/` is
gitignored, so seeded and real signups never get committed.

Writes go through a promise queue and land via a temp file + rename, so two
signups arriving at once can't overwrite each other and a crash mid-write
can't truncate the file. Swapping in SQLite later means reimplementing the
three functions in `server/storage.js` and nothing else.

## Matching

`server/matching.js` groups signups into tables of 3–4. Two people can share a
table only if they picked **the same neighborhood and the same time window** —
a group is always a real place at a real time, never an average of
preferences.

Within each neighborhood the matcher repeatedly takes the time window with the
most still-unassigned people and seats them. Filling the busiest slot first
means the time most people can make gets used while the pool is deepest, and
anyone left over stays available for their other windows.

Group sizes come from `planGroupSizes(n)`, which seats as many people as
possible in 3s and 4s. Every `n >= 3` splits exactly except `n === 5`, which
becomes one table of 4 with a single person waiting.

Whoever's left over is reported as `unmatched`. That's the expected steady
state, not a failure — it's people who have nobody else in their area and slot
yet, and they wait for the next round of signups.

```bash
npm run seed && npm run match
```

## Design system

The visual system is loaded once in `src/main.jsx`, so every screen inherits
it automatically. See [DESIGN.md](./DESIGN.md).

```
shared/            constants + validation, used by client AND server
  constants.js     neighborhoods, time windows, group sizes
  validation.js    one set of rules for the form and the API

server/
  index.js         Express API
  storage.js       JSON-file persistence
  matching.js      the grouping logic
  matching.test.js its tests
  seed.js          fake signups
  report.js        console output for `npm run match`

src/theme/         tokens.css, base.css, index.css
src/components/ui/ Button, Card, Field, Input, Layout, Typography
src/pages/         Home, Signup, Welcome, Admin
```

Build screens from the primitives rather than writing one-off CSS:

```jsx
import { Button, Card, Field, Input, Stack, Text } from '../components/ui'
```

The one rule: **never hardcode a colour, size, radius or font.** Use a
`var(--…)` token from `tokens.css`, or add a new token there if something
genuinely doesn't exist yet.
