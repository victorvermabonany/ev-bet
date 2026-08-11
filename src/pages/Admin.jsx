import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { timeWindowLabel } from '../../shared/constants.js'
import {
  Button,
  Card,
  Container,
  Eyebrow,
  Heading,
  Row,
  Section,
  Stack,
  Text,
} from '../components/ui'
import './Admin.css'

/** Admin view — shows how the current signups would be grouped. */
export default function Admin() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch('/api/matches')
      if (!response.ok) throw new Error(`Request failed: ${response.status}`)
      setData(await response.json())
    } catch (err) {
      setError('Could not load matches. Is the API running?')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <main className="admin">
      <Container>
        <Section>
          <Stack gap="xl">
            <Row gap="md" align="end" className="admin__head">
              <Stack gap="2xs">
                <Eyebrow>Admin</Eyebrow>
                <Heading level={1} size="3xl">
                  Matched groups
                </Heading>
              </Stack>
              <Row gap="2xs">
                <Button variant="secondary" size="sm" onClick={load} disabled={loading}>
                  {loading ? 'Loading…' : 'Refresh'}
                </Button>
                <Button as={Link} to="/signup" variant="ghost" size="sm">
                  Add a signup
                </Button>
              </Row>
            </Row>

            {error && (
              <Card tone="accent" padding="md">
                <Text size="base">{error}</Text>
              </Card>
            )}

            {data && (
              <>
                {/* A plain div, not <Row>: this lays out as its own grid and
                    shouldn't inherit Row's flex display. */}
                <div className="admin__stats">
                  <Stat label="Signups" value={data.stats.signups} />
                  <Stat label="Groups" value={data.stats.groups} />
                  <Stat label="Matched" value={data.stats.matched} />
                  <Stat label="Waiting" value={data.stats.unmatched} />
                </div>

                {data.groups.length === 0 ? (
                  <Card tone="sunken" padding="lg">
                    <Text tone="muted">
                      No groups yet — a table needs three people in the same area at the
                      same time.
                    </Text>
                  </Card>
                ) : (
                  <div className="admin__groups">
                    {data.groups.map((group, i) => (
                      <Card key={group.id} padding="lg" className="admin__group">
                        <Stack gap="md">
                          <Stack gap="3xs">
                            <Eyebrow>Group {i + 1}</Eyebrow>
                            <Heading level={2} size="xl">
                              {group.neighborhood}
                            </Heading>
                            <Text size="sm" tone="accent">
                              {timeWindowLabel(group.timeWindow)}
                            </Text>
                          </Stack>

                          <ul className="admin__members">
                            {group.members.map((member) => (
                              <li key={member.id} className="admin__member">
                                <span className="admin__member-name">{member.name}</span>
                                <span className="admin__member-contact" data-numeric>
                                  {member.contact}
                                </span>
                              </li>
                            ))}
                          </ul>
                        </Stack>
                      </Card>
                    ))}
                  </div>
                )}

                {data.unmatched.length > 0 && (
                  <Stack gap="sm">
                    <Heading level={2} size="xl">
                      Waiting for the next round
                    </Heading>
                    <Text tone="muted" size="base">
                      Nobody else in their area picked the same time yet.
                    </Text>
                    <Card tone="sunken" padding="lg">
                      <ul className="admin__members">
                        {data.unmatched.map((person) => (
                          <li key={person.id} className="admin__member">
                            <span className="admin__member-name">{person.name}</span>
                            <span className="admin__member-contact">
                              {person.neighborhood} ·{' '}
                              {person.timeWindows.map(timeWindowLabel).join(', ')}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </Card>
                  </Stack>
                )}
              </>
            )}
          </Stack>
        </Section>
      </Container>
    </main>
  )
}

function Stat({ label, value }) {
  return (
    <Card tone="sunken" padding="md" className="admin__stat">
      <Text size="sm" tone="subtle">
        {label}
      </Text>
      <span className="admin__stat-value" data-numeric>
        {value}
      </span>
    </Card>
  )
}
