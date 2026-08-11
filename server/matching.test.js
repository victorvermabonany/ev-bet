import assert from 'node:assert/strict'
import test from 'node:test'

import { matchSignups, planGroupSizes } from './matching.js'

let seq = 0
function person(neighborhood, timeWindows, name = `p${++seq}`) {
  return { id: name, name, neighborhood, timeWindows, createdAt: `2026-01-01T00:00:${String(seq).padStart(2, '0')}Z` }
}

test('planGroupSizes splits into 3s and 4s, seating the most people', () => {
  assert.deepEqual(planGroupSizes(0), [])
  assert.deepEqual(planGroupSizes(1), [])
  assert.deepEqual(planGroupSizes(2), [])
  assert.deepEqual(planGroupSizes(3), [3])
  assert.deepEqual(planGroupSizes(4), [4])
  // 5 is the one size that can't be covered exactly — one person waits.
  assert.deepEqual(planGroupSizes(5), [4])
  assert.deepEqual(planGroupSizes(6), [3, 3])
  assert.deepEqual(planGroupSizes(7), [4, 3])
  assert.deepEqual(planGroupSizes(8), [4, 4])
  assert.deepEqual(planGroupSizes(9), [3, 3, 3])
  assert.deepEqual(planGroupSizes(10), [4, 3, 3])
  assert.deepEqual(planGroupSizes(11), [4, 4, 3])
  assert.deepEqual(planGroupSizes(12), [4, 4, 4])
})

test('planGroupSizes never leaves more than 2 people over, above n=5', () => {
  for (let n = 6; n <= 200; n++) {
    const seated = planGroupSizes(n).reduce((a, b) => a + b, 0)
    assert.equal(seated, n, `n=${n} should seat everyone`)
  }
})

test('groups only form from a shared neighbourhood and a shared window', () => {
  const { groups } = matchSignups([
    person('Astoria', ['mon-lunch']),
    person('Astoria', ['mon-lunch']),
    person('Astoria', ['mon-lunch']),
  ])

  assert.equal(groups.length, 1)
  assert.equal(groups[0].neighborhood, 'Astoria')
  assert.equal(groups[0].timeWindow, 'mon-lunch')
  assert.equal(groups[0].members.length, 3)
})

test('same neighbourhood but no shared window produces no group', () => {
  const { groups, unmatched } = matchSignups([
    person('Harlem', ['mon-lunch']),
    person('Harlem', ['tue-lunch']),
    person('Harlem', ['wed-lunch']),
  ])

  assert.equal(groups.length, 0)
  assert.equal(unmatched.length, 3)
})

test('same window but different neighbourhoods produces no group', () => {
  const { groups, unmatched } = matchSignups([
    person('Harlem', ['mon-lunch']),
    person('Astoria', ['mon-lunch']),
    person('Park Slope', ['mon-lunch']),
  ])

  assert.equal(groups.length, 0)
  assert.equal(unmatched.length, 3)
})

test('fewer than three people never form a group', () => {
  const { groups, unmatched } = matchSignups([
    person('Chelsea', ['fri-lunch']),
    person('Chelsea', ['fri-lunch']),
  ])

  assert.equal(groups.length, 0)
  assert.equal(unmatched.length, 2)
})

test('a pool of 7 splits into a 4 and a 3', () => {
  const people = Array.from({ length: 7 }, () => person('Bushwick', ['thu-lunch']))
  const { groups, unmatched } = matchSignups(people)

  assert.deepEqual(groups.map((g) => g.members.length), [4, 3])
  assert.equal(unmatched.length, 0)
})

test('someone left over from one window is still placed via another', () => {
  // Five want Tuesday, so one is left over — but that person also picked
  // Thursday, where three others are waiting.
  const people = [
    person('Midtown', ['tue-lunch']),
    person('Midtown', ['tue-lunch']),
    person('Midtown', ['tue-lunch']),
    person('Midtown', ['tue-lunch']),
    person('Midtown', ['tue-lunch', 'thu-lunch']),
    person('Midtown', ['thu-lunch']),
    person('Midtown', ['thu-lunch']),
  ]

  const { groups, unmatched } = matchSignups(people)

  assert.equal(groups.length, 2)
  assert.deepEqual(groups.map((g) => g.timeWindow).sort(), ['thu-lunch', 'tue-lunch'])
  assert.equal(unmatched.length, 0)
})

test('nobody is placed in two groups at once', () => {
  const people = [
    ...Array.from({ length: 4 }, () => person('Harlem', ['mon-lunch', 'tue-lunch', 'wed-lunch'])),
    ...Array.from({ length: 4 }, () => person('Harlem', ['mon-lunch', 'tue-lunch', 'wed-lunch'])),
  ]

  const { groups } = matchSignups(people)
  const seen = new Set()
  for (const group of groups) {
    for (const member of group.members) {
      assert.ok(!seen.has(member.id), `${member.id} was placed twice`)
      seen.add(member.id)
    }
  }
})

test('every member of a group actually picked that window and area', () => {
  const people = [
    ...Array.from({ length: 5 }, () => person('Flushing', ['sat-brunch', 'mon-lunch'])),
    ...Array.from({ length: 3 }, () => person('Flushing', ['mon-lunch'])),
    ...Array.from({ length: 4 }, () => person('Chelsea', ['sun-brunch'])),
  ]

  const { groups } = matchSignups(people)
  assert.ok(groups.length > 0)

  for (const group of groups) {
    for (const member of group.members) {
      assert.equal(member.neighborhood, group.neighborhood)
      assert.ok(member.timeWindows.includes(group.timeWindow))
    }
    assert.ok(group.members.length >= 3 && group.members.length <= 4)
  }
})

test('matching is deterministic across runs', () => {
  const people = [
    ...Array.from({ length: 6 }, () => person('Greenpoint', ['wed-lunch', 'fri-lunch'])),
    ...Array.from({ length: 5 }, () => person('Greenpoint', ['fri-lunch'])),
  ]

  const first = matchSignups(people)
  const second = matchSignups([...people])

  assert.deepEqual(
    first.groups.map((g) => g.members.map((m) => m.id)),
    second.groups.map((g) => g.members.map((m) => m.id)),
  )
})

test('empty input is handled', () => {
  const { groups, unmatched, stats } = matchSignups([])
  assert.deepEqual(groups, [])
  assert.deepEqual(unmatched, [])
  assert.equal(stats.signups, 0)
})
