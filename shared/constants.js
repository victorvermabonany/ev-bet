/**
 * Domain constants shared by the client form and the server matcher.
 *
 * Both import from here so the options a person can pick are always the
 * same set the matching logic reasons about.
 */

/**
 * Time windows are deliberately concrete — one slot per day rather than a
 * broad "weekday lunch" bucket. Two people only match if they picked the
 * *same* slot, so overlap stays unambiguous. The form still offers
 * "Weekday lunch" / "Weekend brunch" as quick selects; those just tick the
 * underlying days.
 */
export const TIME_WINDOWS = [
  { id: 'mon-lunch', day: 'Monday', short: 'Mon', group: 'weekday' },
  { id: 'tue-lunch', day: 'Tuesday', short: 'Tue', group: 'weekday' },
  { id: 'wed-lunch', day: 'Wednesday', short: 'Wed', group: 'weekday' },
  { id: 'thu-lunch', day: 'Thursday', short: 'Thu', group: 'weekday' },
  { id: 'fri-lunch', day: 'Friday', short: 'Fri', group: 'weekday' },
  { id: 'sat-brunch', day: 'Saturday', short: 'Sat', group: 'weekend' },
  { id: 'sun-brunch', day: 'Sunday', short: 'Sun', group: 'weekend' },
]

export const TIME_WINDOW_GROUPS = [
  {
    id: 'weekday',
    label: 'Weekday lunch',
    hint: '12–2pm, Monday to Friday',
    quickSelect: 'All weekdays',
  },
  {
    id: 'weekend',
    label: 'Weekend brunch',
    hint: '11am–2pm, Saturday and Sunday',
    quickSelect: 'Both days',
  },
]

export const TIME_WINDOW_IDS = TIME_WINDOWS.map((w) => w.id)

/** Human label for a window id, e.g. 'mon-lunch' → 'Monday lunch'. */
export function timeWindowLabel(id) {
  const window = TIME_WINDOWS.find((w) => w.id === id)
  if (!window) return id
  return `${window.day} ${window.group === 'weekend' ? 'brunch' : 'lunch'}`
}

/** NYC neighbourhoods, grouped by borough for the select. */
export const NEIGHBORHOODS_BY_BOROUGH = [
  {
    borough: 'Manhattan',
    areas: [
      'Upper West Side',
      'Upper East Side',
      'Harlem',
      'Midtown',
      'Chelsea',
      'West Village',
      'East Village',
      'Lower East Side',
      'SoHo / Tribeca',
      'Financial District',
    ],
  },
  {
    borough: 'Brooklyn',
    areas: [
      'Williamsburg',
      'Greenpoint',
      'Bushwick',
      'Bed-Stuy',
      'Fort Greene / Clinton Hill',
      'Park Slope',
      'Prospect Heights',
      'Crown Heights',
      'Carroll Gardens / Cobble Hill',
      'Downtown Brooklyn',
    ],
  },
  {
    borough: 'Queens',
    areas: [
      'Long Island City',
      'Astoria',
      'Sunnyside / Woodside',
      'Jackson Heights',
      'Forest Hills',
      'Flushing',
    ],
  },
  {
    borough: 'The Bronx',
    areas: ['Mott Haven', 'Fordham', 'Riverdale'],
  },
  {
    borough: 'Staten Island',
    areas: ['St. George', 'Stapleton'],
  },
]

export const NEIGHBORHOODS = NEIGHBORHOODS_BY_BOROUGH.flatMap((b) => b.areas)

/** Groups are kept small on purpose — big enough to have a table, small
 *  enough that everyone actually talks. */
export const GROUP_MIN = 3
export const GROUP_MAX = 4
