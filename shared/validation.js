import { NEIGHBORHOODS, TIME_WINDOW_IDS } from './constants.js'

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/
const PHONE_RE = /^\+?[\d\s().-]{10,20}$/

/** Contact can be either an email or a phone number — figure out which. */
export function detectContactType(raw) {
  const value = String(raw ?? '').trim()
  if (EMAIL_RE.test(value)) return 'email'
  // Require a plausible number of digits so "hello" or "1234" don't pass.
  const digits = value.replace(/\D/g, '')
  if (PHONE_RE.test(value) && digits.length >= 10 && digits.length <= 15) return 'phone'
  return null
}

/**
 * Validate a signup payload. Returns { valid, errors, value } where `value`
 * is the normalised record ready to store. Used by the form for inline
 * errors and by the API so the server never trusts the client.
 */
export function validateSignup(input = {}) {
  const errors = {}

  const name = String(input.name ?? '').trim()
  if (!name) errors.name = 'Please tell us your name.'
  else if (name.length > 80) errors.name = 'That name is a little too long.'

  const contact = String(input.contact ?? '').trim()
  const contactType = detectContactType(contact)
  if (!contact) errors.contact = 'We need a way to reach you.'
  else if (!contactType) errors.contact = 'Enter a valid email address or phone number.'

  const neighborhood = String(input.neighborhood ?? '').trim()
  if (!neighborhood) errors.neighborhood = 'Pick the area you want to eat in.'
  else if (!NEIGHBORHOODS.includes(neighborhood)) {
    errors.neighborhood = 'Pick one of the listed areas.'
  }

  const rawWindows = Array.isArray(input.timeWindows) ? input.timeWindows : []
  const timeWindows = TIME_WINDOW_IDS.filter((id) => rawWindows.includes(id))
  if (timeWindows.length === 0) {
    errors.timeWindows = 'Choose at least one time that works for you.'
  }

  return {
    valid: Object.keys(errors).length === 0,
    errors,
    value: { name, contact, contactType, neighborhood, timeWindows },
  }
}
