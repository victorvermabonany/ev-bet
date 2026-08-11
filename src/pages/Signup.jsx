import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  NEIGHBORHOODS_BY_BOROUGH,
  TIME_WINDOWS,
  TIME_WINDOW_GROUPS,
} from '../../shared/constants.js'
import { validateSignup } from '../../shared/validation.js'
import {
  Button,
  Card,
  Checkbox,
  Container,
  Field,
  Fieldset,
  Heading,
  Input,
  Row,
  Select,
  Stack,
  Text,
} from '../components/ui'
import './Signup.css'

const BOROUGH_GROUPS = NEIGHBORHOODS_BY_BOROUGH.map((b) => ({
  label: b.borough,
  options: b.areas,
}))

const EMPTY = { name: '', contact: '', neighborhood: '', timeWindows: [] }

export default function Signup() {
  const navigate = useNavigate()
  const [form, setForm] = useState(EMPTY)
  const [errors, setErrors] = useState({})
  const [attempted, setAttempted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)

  // Stay quiet until the first submit attempt, then keep errors in step with
  // what's actually in the form — so a message clears as soon as it's fixed
  // rather than lingering until the next submit.
  useEffect(() => {
    if (attempted) setErrors(validateSignup(form).errors)
  }, [form, attempted])

  function update(patch) {
    setForm((current) => ({ ...current, ...patch }))
  }

  function toggleWindow(id) {
    setForm((current) => ({
      ...current,
      timeWindows: current.timeWindows.includes(id)
        ? current.timeWindows.filter((w) => w !== id)
        : [...current.timeWindows, id],
    }))
  }

  /** "All weekdays" / "Both days" — tick the whole group, or clear it. */
  function toggleGroup(groupId) {
    const ids = TIME_WINDOWS.filter((w) => w.group === groupId).map((w) => w.id)
    setForm((current) => {
      const allOn = ids.every((id) => current.timeWindows.includes(id))
      return {
        ...current,
        timeWindows: allOn
          ? current.timeWindows.filter((id) => !ids.includes(id))
          : [...new Set([...current.timeWindows, ...ids])],
      }
    })
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setSubmitError(null)
    setAttempted(true)

    const { valid, errors: found } = validateSignup(form)
    setErrors(found)
    if (!valid) return

    setSubmitting(true)
    try {
      const response = await fetch('/api/signups', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })

      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        // Surface server-side field errors in the same place as local ones.
        if (body.errors) {
          setErrors(body.errors)
          return
        }
        throw new Error(body.error || 'Signup failed')
      }

      const { signup } = await response.json()
      navigate('/welcome', { state: { name: signup.name } })
    } catch (error) {
      setSubmitError("We couldn't save that just now. Please try again.")
      console.error(error)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="signup">
      <Container width="narrow">
        <Stack gap="xl" className="signup__inner">
          <Stack gap="sm">
            <Heading level={1} size="3xl">
              Find your lunch table
            </Heading>
            <Text size="lg" tone="muted" measure>
              Tell us where you eat and when you&rsquo;re free. We&rsquo;ll seat you with three
              or four neighbours.
            </Text>
          </Stack>

          <Card padding="xl" as="form" onSubmit={handleSubmit} noValidate>
            <Stack gap="lg" align="stretch">
              <Field label="Your name" error={errors.name}>
                {(props) => (
                  <Input
                    {...props}
                    name="name"
                    autoComplete="name"
                    placeholder="Alex Rivera"
                    value={form.name}
                    onChange={(e) => update({ name: e.target.value })}
                  />
                )}
              </Field>

              <Field
                label="Email or phone"
                hint="However you'd rather hear from us about your group."
                error={errors.contact}
              >
                {(props) => (
                  <Input
                    {...props}
                    name="contact"
                    placeholder="alex@example.com"
                    value={form.contact}
                    onChange={(e) => update({ contact: e.target.value })}
                  />
                )}
              </Field>

              <Field
                label="Where in NYC?"
                hint="Pick the area you'd actually want to eat in."
                error={errors.neighborhood}
              >
                {(props) => (
                  <Select
                    {...props}
                    name="neighborhood"
                    groups={BOROUGH_GROUPS}
                    placeholder="Choose a neighborhood"
                    value={form.neighborhood}
                    onChange={(e) => update({ neighborhood: e.target.value })}
                  />
                )}
              </Field>

              <Fieldset
                legend="When are you free?"
                hint="Choose as many as you like — more options mean an easier match."
                error={errors.timeWindows}
              >
                <Stack gap="md" align="stretch" className="signup__windows">
                  {TIME_WINDOW_GROUPS.map((group) => {
                    const windows = TIME_WINDOWS.filter((w) => w.group === group.id)
                    const allOn = windows.every((w) => form.timeWindows.includes(w.id))

                    return (
                      <div key={group.id} className="signup__window-group">
                        <div className="signup__window-head">
                          <div>
                            <Text size="base" className="signup__window-title">
                              {group.label}
                            </Text>
                            <Text size="sm" tone="subtle">
                              {group.hint}
                            </Text>
                          </div>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            onClick={() => toggleGroup(group.id)}
                          >
                            {allOn ? 'Clear' : group.quickSelect}
                          </Button>
                        </div>

                        <Row gap="2xs">
                          {windows.map((window) => (
                            <Checkbox
                              key={window.id}
                              name="timeWindows"
                              value={window.id}
                              label={window.short}
                              checked={form.timeWindows.includes(window.id)}
                              onChange={() => toggleWindow(window.id)}
                            />
                          ))}
                        </Row>
                      </div>
                    )
                  })}
                </Stack>
              </Fieldset>

              {submitError && (
                <Text size="base" className="signup__submit-error" role="alert">
                  {submitError}
                </Text>
              )}

              <Row gap="sm" align="center" className="signup__actions">
                <Button type="submit" size="lg" disabled={submitting}>
                  {submitting ? 'Saving…' : 'Join a table'}
                </Button>
                <Text size="sm" tone="subtle">
                  No spam. We only write when there&rsquo;s a group.
                </Text>
              </Row>
            </Stack>
          </Card>
        </Stack>
      </Container>
    </main>
  )
}
