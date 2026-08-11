/**
 * Print the current matching to the console. Run with `npm run match`.
 */
import { timeWindowLabel } from '../shared/constants.js'
import { readSignups } from './storage.js'
import { matchSignups } from './matching.js'

const signups = await readSignups()
const { groups, unmatched, stats } = matchSignups(signups)

if (signups.length === 0) {
  console.log('No signups yet. Run `npm run seed` for sample data.')
  process.exit(0)
}

console.log(`\n${groups.length} group${groups.length === 1 ? '' : 's'} from ${stats.signups} signups\n`)

for (const [i, group] of groups.entries()) {
  console.log(`Group ${i + 1} — ${group.neighborhood}, ${timeWindowLabel(group.timeWindow)}`)
  for (const member of group.members) {
    console.log(`    ${member.name.padEnd(20)} ${member.contact}`)
  }
  console.log('')
}

if (unmatched.length > 0) {
  console.log(`Waiting for the next round (${unmatched.length}):`)
  for (const person of unmatched) {
    const windows = person.timeWindows.map(timeWindowLabel).join(', ')
    console.log(`    ${person.name.padEnd(20)} ${person.neighborhood} — ${windows}`)
  }
  console.log('')
}

console.log(`Matched ${stats.matched}/${stats.signups}\n`)
