import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import { randomUUID } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export const DATA_DIR = path.join(ROOT, 'data')
export const SIGNUPS_FILE = path.join(DATA_DIR, 'signups.json')

/**
 * A JSON file is the whole database for now. It's the fastest thing to
 * stand up and inspect by hand; swapping it for SQLite later only means
 * reimplementing the three functions below.
 */

export async function readSignups() {
  try {
    const raw = await readFile(SIGNUPS_FILE, 'utf8')
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch (error) {
    // No file yet just means nobody has signed up.
    if (error.code === 'ENOENT') return []
    throw error
  }
}

// Every write goes through this promise chain, so two requests arriving at
// once can't both read the same list and overwrite each other's signup.
let writeQueue = Promise.resolve()

function enqueue(task) {
  const result = writeQueue.then(task, task)
  // Keep the chain alive even if this task rejects.
  writeQueue = result.then(
    () => undefined,
    () => undefined,
  )
  return result
}

async function writeSignups(signups) {
  await mkdir(DATA_DIR, { recursive: true })
  // Write to a temp file then rename, so a crash mid-write can't leave a
  // truncated file behind.
  const tmp = `${SIGNUPS_FILE}.${randomUUID()}.tmp`
  await writeFile(tmp, `${JSON.stringify(signups, null, 2)}\n`, 'utf8')
  await rename(tmp, SIGNUPS_FILE)
}

/** Append one signup and return the stored record. */
export function addSignup(signup) {
  return enqueue(async () => {
    const signups = await readSignups()
    const record = {
      id: randomUUID(),
      createdAt: new Date().toISOString(),
      ...signup,
    }
    signups.push(record)
    await writeSignups(signups)
    return record
  })
}

/** Replace the whole list — used by the seed script. */
export function replaceSignups(signups) {
  return enqueue(async () => {
    await writeSignups(signups)
    return signups
  })
}
