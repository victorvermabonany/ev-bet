# EV Bet — visual system

Calm and editorial. Cream paper, warm ink, terracotta accent, serif
headlines with real room to breathe. It should feel like a well-designed
journal, not a tech dashboard.

All values live as CSS custom properties in `src/theme/tokens.css`. That
file is the single source of truth — this document just explains the
intent behind it.

## Typography

| Role | Family | Token |
| --- | --- | --- |
| Headlines | Fraunces Variable | `--font-serif` |
| Body, UI, data | Inter Variable | `--font-sans` |

Both are bundled locally through `@fontsource`, so there is no runtime
request to Google Fonts and the app renders identically offline or inside
a webview.

Fraunces is loaded from `full.css` rather than the default `index.css`,
because the default ships the weight axis only. The character of the
typeface lives in its other axes, which `--font-serif-settings` drives:

- `SOFT` — rounds the terminals, the main source of the warmth
- `WONK` — the friendlier single-storey glyphs
- `opsz` — optical size, so display type isn't just body type scaled up

A bare `<h1>`–`<h6>` is already serif with the right axes and tracking, so
markup that skips the components still looks right.

Sizes run `--text-xs` → `--text-5xl`. Everything from `--text-lg` up is a
`clamp()`, so headlines scale with the viewport instead of stepping at
breakpoints. Display type is set at `--weight-regular`; Fraunces reads
better light and large than bold and small.

Numbers use tabular figures automatically via the `[data-numeric]`
attribute — worth reaching for on any odds or percentage column.

## Colour

Warm throughout. There is no pure white, no pure black, and no pure grey
anywhere in the palette; even the border colours are warm-tinted.

| Token | Use |
| --- | --- |
| `--color-canvas` `#fbf6ee` | page background, warm cream |
| `--color-surface` `#fffdf9` | raised cards |
| `--color-surface-sunken` `#f4ebdf` | wells and inset panels |
| `--color-ink` `#2c2018` | headlines and body, warm near-black |
| `--color-ink-muted` `#6d5c4d` | secondary copy |
| `--color-ink-subtle` `#9a8878` | eyebrows, captions, metadata |
| `--color-accent` `#c2602f` | terracotta — primary actions |
| `--color-accent-strong` `#a44c21` | hover and pressed |
| `--color-accent-soft` `#f6e5d8` | tinted backgrounds |
| `--color-olive` `#6f7a52` | positive value |
| `--color-clay` `#9c6b4f` | neutral highlight |

This is a light theme by design. There is no dark mode, and adding one
would mean re-deriving the palette rather than inverting it.

## Space

A 4px base scale, `--space-3xs` (4px) → `--space-4xl` (128px), with the
top end deliberately roomy. Page bands use `Section`, which sets a fluid
`clamp(64px, 9vh, 128px)` of vertical padding. Horizontal gutters come
from `--gutter`, which is itself fluid.

Prose is capped at `--measure-prose` (34ch) so lines stay comfortable.
Page width is `--width-content` (68rem), or `--width-narrow` (46rem) for
centred editorial columns.

Prefer `Stack` and `Row` over one-off margins — spacing then always lands
on the scale.

## Shape

Everything is rounded. `--radius-xs` (8px) for small chips through
`--radius-xl` (40px) for feature panels, plus `--radius-pill` for
buttons. Cards sit at `--radius-lg` (28px).

Elevation is warm, diffuse and low-contrast — the shadows read as light
falling on paper rather than as drop shadows. Reach for `--shadow-md` on
cards and `--shadow-accent` under terracotta buttons.

## Motion

Unhurried and never bouncy: `--ease-out` with `--duration-fast` (140ms)
for hovers and `--duration-base` (220ms) for state changes.
`prefers-reduced-motion` is honoured globally in `base.css`.

## Focus

One treatment for the whole app, set in `base.css`: a 2px terracotta
`:focus-visible` ring with 3px of offset. Don't remove it per-component.
