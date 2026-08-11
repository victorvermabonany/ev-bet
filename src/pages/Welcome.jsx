import { Link, useLocation } from 'react-router-dom'

import { Button, Container, Heading, Row, Stack, Text } from '../components/ui'
import './Welcome.css'

/** Confirmation screen, shown after a successful signup. */
export default function Welcome() {
  const { state } = useLocation()
  const name = state?.name?.split(' ')[0]

  return (
    <main className="welcome">
      <div className="welcome__glow" aria-hidden="true" />

      <Container width="narrow">
        <Stack gap="xl" align="center">
          <span className="welcome__mark" aria-hidden="true">
            <svg width="30" height="23" viewBox="0 0 13 10" fill="none">
              <path
                d="M1.5 5.2L4.7 8.4L11.2 1.6"
                stroke="currentColor"
                strokeWidth="1.9"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>

          <Stack gap="md" align="center">
            <Heading level={1} size="4xl">
              You&rsquo;re in{name ? `, ${name}` : ''}!
            </Heading>
            <Text size="xl" tone="muted" measure>
              We&rsquo;ll match you with a small group soon.
            </Text>
          </Stack>

          <Row gap="sm" align="center" className="welcome__actions">
            <Button as={Link} to="/" variant="secondary" size="md">
              Back home
            </Button>
          </Row>
        </Stack>
      </Container>
    </main>
  )
}
