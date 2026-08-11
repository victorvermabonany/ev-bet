/**
 * Replace the stored signups with a fixed set of fake ones.
 *
 * The set is built to exercise every branch of the matcher rather than to
 * look impressive:
 *
 *   Park Slope   4 on Saturday  → one full group of 4
 *   Williamsburg 3 on Wednesday → one minimum-size group of 3
 *   Midtown      5 on Tuesday   → group of 4, one person left over (n=5
 *                                 can't split into 3s and 4s)
 *   Astoria      2 on Thursday  → nobody matched, too few for a table
 *
 * Run with `npm run seed`. It overwrites data/signups.json.
 */
import { replaceSignups } from './storage.js'

const FAKE_SIGNUPS = [
  // Park Slope — four people who all picked Saturday brunch.
  ['Maya Alvarez', 'maya.alvarez@example.com', 'Park Slope', ['sat-brunch', 'sun-brunch']],
  ['Daniel Okafor', '(212) 555-0143', 'Park Slope', ['sat-brunch']],
  ['Priya Raman', 'priya.raman@example.com', 'Park Slope', ['sat-brunch', 'fri-lunch']],
  ['Tom Beckett', 'tom.beckett@example.com', 'Park Slope', ['sat-brunch']],

  // Williamsburg — exactly three on Wednesday, the smallest viable table.
  ['Alexis Chen', 'alexis.chen@example.com', 'Williamsburg', ['wed-lunch', 'thu-lunch']],
  ['Jonah Feldman', '+1 646 555 0198', 'Williamsburg', ['wed-lunch']],
  ['Rosa Iglesias', 'rosa.iglesias@example.com', 'Williamsburg', ['wed-lunch', 'mon-lunch']],

  // Midtown — five on Tuesday, so one person waits for the next round.
  ['Kwame Boateng', 'kwame.boateng@example.com', 'Midtown', ['tue-lunch', 'wed-lunch']],
  ['Hannah Weiss', 'hannah.weiss@example.com', 'Midtown', ['tue-lunch']],
  ['Léa Moreau', '917-555-0176', 'Midtown', ['tue-lunch', 'thu-lunch']],
  ['Sam Oyelaran', 'sam.oyelaran@example.com', 'Midtown', ['tue-lunch']],
  ['Ingrid Halvorsen', 'ingrid.h@example.com', 'Midtown', ['tue-lunch']],

  // Astoria — only two people, so no table forms at all.
  ['Nadia Rahman', 'nadia.rahman@example.com', 'Astoria', ['thu-lunch']],
  ['Peter Lombardi', 'peter.lombardi@example.com', 'Astoria', ['thu-lunch', 'sun-brunch']],
]

const signups = FAKE_SIGNUPS.map(([name, contact, neighborhood, timeWindows], i) => ({
  id: `seed-${String(i + 1).padStart(2, '0')}`,
  // Staggered timestamps so ordering is stable and realistic.
  createdAt: new Date(Date.UTC(2026, 7, 10, 9, i * 7)).toISOString(),
  name,
  contact,
  contactType: contact.includes('@') ? 'email' : 'phone',
  neighborhood,
  timeWindows,
}))

await replaceSignups(signups)
console.log(`Seeded ${signups.length} signups → data/signups.json`)
