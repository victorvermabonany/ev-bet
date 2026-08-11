import { GROUP_MAX, GROUP_MIN, TIME_WINDOW_IDS } from '../shared/constants.js'

/**
 * Decide how to split `n` people into groups of GROUP_MIN..GROUP_MAX.
 *
 * Returns the sizes that seat the most people, preferring fuller groups
 * when there's a tie. Every n >= 3 splits cleanly into 3s and 4s except
 * n === 5, which becomes one group of 4 with a single person left over.
 *
 *   3 → [3]      6 → [3,3]    9  → [3,3,3]
 *   4 → [4]      7 → [4,3]    10 → [4,3,3]
 *   5 → [4]      8 → [4,4]    11 → [4,4,3]
 */
export function planGroupSizes(n) {
  let best = { covered: 0, big: 0, small: 0 }

  for (let big = Math.floor(n / GROUP_MAX); big >= 0; big--) {
    const small = Math.floor((n - big * GROUP_MAX) / GROUP_MIN)
    const covered = big * GROUP_MAX + small * GROUP_MIN
    // Seat the most people; break ties toward fewer, fuller groups.
    if (covered > best.covered || (covered === best.covered && big > best.big)) {
      best = { covered, big, small }
    }
  }

  return [
    ...Array(best.big).fill(GROUP_MAX),
    ...Array(best.small).fill(GROUP_MIN),
  ]
}

/**
 * Group signups into lunch tables.
 *
 * Two people can share a table only if they picked the same neighbourhood
 * *and* at least one identical time window — a group is always a real
 * place at a real time, never a loose average of preferences.
 *
 * Within each neighbourhood we repeatedly take the time window with the
 * most still-unassigned people and seat them. Taking the busiest window
 * first means the slot most people can make gets filled while the pool is
 * deepest, and anyone left over stays available for their other windows.
 *
 * Returns { groups, unmatched, stats }. `unmatched` is expected, not a
 * failure: it's everyone who has no fellow diners in their area and slot
 * yet, and they simply wait for the next round of signups.
 */
export function matchSignups(signups = []) {
  const assigned = new Set()
  const groups = []

  // Stable input order → stable output, so the admin view doesn't reshuffle
  // between refreshes.
  const ordered = [...signups].sort((a, b) => {
    const byDate = String(a.createdAt ?? '').localeCompare(String(b.createdAt ?? ''))
    return byDate !== 0 ? byDate : String(a.id).localeCompare(String(b.id))
  })

  const byNeighborhood = new Map()
  for (const person of ordered) {
    if (!byNeighborhood.has(person.neighborhood)) {
      byNeighborhood.set(person.neighborhood, [])
    }
    byNeighborhood.get(person.neighborhood).push(person)
  }

  const neighborhoods = [...byNeighborhood.keys()].sort()

  for (const neighborhood of neighborhoods) {
    const people = byNeighborhood.get(neighborhood)

    // Keep seating tables here until no window has enough people left.
    for (;;) {
      let chosenWindow = null
      let chosenPool = []

      for (const windowId of TIME_WINDOW_IDS) {
        const pool = people.filter(
          (p) => !assigned.has(p.id) && p.timeWindows.includes(windowId),
        )
        // Strictly greater keeps the earliest window on a tie, which makes
        // the result deterministic.
        if (pool.length > chosenPool.length) {
          chosenWindow = windowId
          chosenPool = pool
        }
      }

      if (!chosenWindow || chosenPool.length < GROUP_MIN) break

      let cursor = 0
      for (const size of planGroupSizes(chosenPool.length)) {
        const members = chosenPool.slice(cursor, cursor + size)
        cursor += size
        for (const member of members) assigned.add(member.id)
        groups.push({
          id: `${neighborhood}::${chosenWindow}::${groups.length + 1}`,
          neighborhood,
          timeWindow: chosenWindow,
          members,
        })
      }
    }
  }

  const unmatched = ordered.filter((p) => !assigned.has(p.id))

  return {
    groups,
    unmatched,
    stats: {
      signups: ordered.length,
      groups: groups.length,
      matched: ordered.length - unmatched.length,
      unmatched: unmatched.length,
    },
  }
}
