# Ember

A React app built with Vite, on a warm editorial design system.

`Ember` is a placeholder name — it lives in `src/config.js` alongside the
tagline, so changing it there updates every screen that shows the wordmark.

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # production bundle → dist/
npm run preview  # serve the built bundle
```

## Design system

The visual system is set up first and loaded once in `src/main.jsx`, so
every screen built after this inherits it automatically. See
[DESIGN.md](./DESIGN.md) for the full reference.

```
src/theme/
  index.css     entrypoint — fonts + tokens + base
  tokens.css    all colour, type, spacing, radius, shadow variables
  base.css      light reset and element defaults wired to the tokens

src/components/ui/
  Button.jsx      primary / secondary / ghost, three sizes
  Card.jsx        surface / sunken / accent
  Layout.jsx      Container, Stack, Row, Section
  Typography.jsx  Heading, Text, Eyebrow
  index.js        barrel export

src/pages/
  Home.jsx        the homepage
```

Build screens from these primitives rather than writing one-off CSS:

```jsx
import { Button, Card, Container, Heading, Stack, Text } from '../components/ui'
```

The one rule: **never hardcode a colour, size, radius or font.** Use a
`var(--…)` token from `tokens.css`, or add a new token there if something
genuinely doesn't exist yet.
