import express from 'express'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { validateSignup } from '../shared/validation.js'
import { addSignup, readSignups } from './storage.js'
import { matchSignups } from './matching.js'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const PORT = Number(process.env.PORT) || 3001

const app = express()
app.use(express.json())

app.get('/api/health', (req, res) => {
  res.json({ ok: true })
})

app.post('/api/signups', async (req, res, next) => {
  try {
    // Re-validate server-side: the client's checks are for helpful inline
    // errors, not a guarantee.
    const { valid, errors, value } = validateSignup(req.body)
    if (!valid) return res.status(400).json({ errors })

    const record = await addSignup(value)
    res.status(201).json({ signup: record })
  } catch (error) {
    next(error)
  }
})

app.get('/api/signups', async (req, res, next) => {
  try {
    res.json({ signups: await readSignups() })
  } catch (error) {
    next(error)
  }
})

/** The admin view reads this to show how people would be grouped today. */
app.get('/api/matches', async (req, res, next) => {
  try {
    res.json(matchSignups(await readSignups()))
  } catch (error) {
    next(error)
  }
})

// In production the API also serves the built client.
const dist = path.join(ROOT, 'dist')
app.use(express.static(dist))
app.get(/^(?!\/api\/).*/, (req, res, next) => {
  res.sendFile(path.join(dist, 'index.html'), (error) => {
    // Before the first `npm run build` there's nothing to serve; in dev
    // that's fine because Vite serves the client instead.
    if (error) next()
  })
})

app.use((error, req, res, next) => {
  console.error(error)
  res.status(500).json({ error: 'Something went wrong on our end.' })
})

app.listen(PORT, () => {
  console.log(`API listening on http://localhost:${PORT}`)
})
