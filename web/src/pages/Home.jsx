import { Button, Container, Eyebrow, Heading, Row, Stack, Text } from '../components/ui'
import './Home.css'

export default function Home() {
  return (
    <main className="home">
      <div className="home__glow" aria-hidden="true" />

      <Container width="narrow" className="home__inner">
        <Stack gap="2xl" align="center">
          <Eyebrow>Positive expected value</Eyebrow>

          <Stack gap="lg" align="center">
            <Heading level={1} size="5xl" className="home__wordmark">
              EV&nbsp;Bet
            </Heading>

            <Text size="xl" tone="muted" measure>
              A calmer way to find an edge.
            </Text>
          </Stack>

          <Row gap="sm" align="center" className="home__actions">
            <Button size="lg">Get Started</Button>
          </Row>
        </Stack>
      </Container>
    </main>
  )
}
