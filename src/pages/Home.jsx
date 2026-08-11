import { Link } from 'react-router-dom'

import { APP_NAME, APP_TAGLINE } from '../config.js'
import { Button, Container, Heading, Row, Stack, Text } from '../components/ui'
import './Home.css'

export default function Home() {
  return (
    <main className="home">
      <div className="home__glow" aria-hidden="true" />

      <Container width="narrow" className="home__inner">
        <Stack gap="2xl" align="center">
          <Stack gap="lg" align="center">
            <Heading level={1} size="5xl" className="home__wordmark">
              {APP_NAME}
            </Heading>

            <Text size="xl" tone="muted" measure>
              {APP_TAGLINE}
            </Text>
          </Stack>

          <Row gap="sm" align="center" className="home__actions">
            <Button as={Link} to="/signup" size="lg">
              Get Started
            </Button>
          </Row>
        </Stack>
      </Container>
    </main>
  )
}
