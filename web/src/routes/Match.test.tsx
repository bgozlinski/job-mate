import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { expect, test } from 'vitest'

import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { History, MatchDetail } from './History'
import { Match } from './Match'

const RESUME = {
  id: 'r1',
  content: 'Ten years of Python.',
  target_role: 'Backend developer',
  original_filename: 'cv.pdf',
  created_at: '2026-09-07T10:00:00Z',
}

const POSTING = {
  id: 'd1',
  title: 'Python Developer — DCV',
  source_url: null,
  metadata: {},
  chunk_count: 3,
  created_at: '2026-09-07T11:00:00Z',
}

const MATCH = {
  id: 'm1',
  document_id: 'd1',
  document_title: 'Python Developer — DCV',
  resume_id: 'r1',
  score: 0.75,
  matched_keywords: ['python', 'postgresql'],
  missing_keywords: ['kubernetes'],
  suggestions: ['Shipped a service on Kubernetes'],
  notes: ['The resume does not evidence Kubernetes'],
  retrieved_chunk_ids: ['c1', 'c2'],
  matched_evidence: { python: 'Ten years of Python' },
  created_at: '2026-09-07T12:00:00Z',
}

function show(at = '/match') {
  return render(
    <Providers client={createQueryClient()}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="/match" element={<Match />} />
          <Route path="/matches" element={<History />} />
          <Route path="/matches/:matchId" element={<MatchDetail />} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  )
}

function pickable(): void {
  server.use(
    http.get('/api/resumes', () => HttpResponse.json([RESUME])),
    http.get('/api/documents', () => HttpResponse.json([POSTING])),
  )
}

async function choosePair(): Promise<void> {
  // Waiting for the options, not for the selects. Both selects render at once
  // with only their placeholder, so a query for the control succeeds while
  // the lists are still in flight -- and selecting then fails on a value that
  // has not arrived.
  await screen.findByRole('option', { name: /cv\.pdf/ })
  await screen.findByRole('option', { name: 'Python Developer — DCV' })

  await userEvent.selectOptions(screen.getByLabelText('Resume'), 'r1')
  await userEvent.selectOptions(screen.getByLabelText('Job posting'), 'd1')
  await userEvent.click(screen.getByRole('button', { name: 'Match' }))
}

test('a match reports the score the API computed', async () => {
  // The number is never worked out here: it is a coverage ratio computed in
  // Python so it can be reproduced and explained.
  pickable()
  server.use(
    http.post('/api/resumes/:id/match', () => HttpResponse.json(MATCH)),
  )

  show()
  await choosePair()

  expect(await screen.findByRole('heading', { name: /75% match/ })).toBeInTheDocument()
})

test('suggestions and notes stay two lists', async () => {
  // They come back separately on purpose: one is text to put in the resume,
  // the other is a remark about it. Merged, "the resume does not evidence
  // Kubernetes" reads as a bullet point to paste in.
  pickable()
  server.use(http.post('/api/resumes/:id/match', () => HttpResponse.json(MATCH)))

  show()
  await choosePair()

  expect(
    await screen.findByRole('heading', { name: 'Suggested bullet points' }),
  ).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Notes on the resume' })).toBeInTheDocument()
})

test('a covered requirement shows what the model quoted for it', async () => {
  // Without the evidence a verdict has to be taken on trust; with it a
  // candidate can disagree.
  pickable()
  server.use(http.post('/api/resumes/:id/match', () => HttpResponse.json(MATCH)))

  show()
  await choosePair()

  expect(await screen.findByText('Ten years of Python')).toBeInTheDocument()
})

test('the pairing sent is the one that was chosen', async () => {
  const sent: { resume: string; document: string }[] = []
  pickable()
  server.use(
    http.post('/api/resumes/:id/match', async ({ request, params }) => {
      const body = (await request.json()) as { document_id: string }
      sent.push({ resume: String(params.id), document: body.document_id })

      return HttpResponse.json(MATCH)
    }),
  )

  show()
  await choosePair()

  await waitFor(() => {
    expect(sent).toEqual([{ resume: 'r1', document: 'd1' }])
  })
})

test('an empty knowledge base points at where to fix it', async () => {
  server.use(
    http.get('/api/resumes', () => HttpResponse.json([RESUME])),
    http.get('/api/documents', () => HttpResponse.json([])),
  )

  show()

  expect(await screen.findByRole('link', { name: 'Add a job posting' })).toBeInTheDocument()
})

test('having no resumes points at where to fix that instead', async () => {
  server.use(
    http.get('/api/resumes', () => HttpResponse.json([])),
    http.get('/api/documents', () => HttpResponse.json([POSTING])),
  )

  show()

  expect(await screen.findByRole('link', { name: 'Add one' })).toBeInTheDocument()
})

test('the rate limit says how long to wait, not just that it was hit', async () => {
  // Matching costs an LLM call on top of its embeddings and is capped per
  // account (NFR-2). "Too many requests" alone leaves the user pressing the
  // button to find out when it will work again.
  pickable()
  server.use(
    http.post('/api/resumes/:id/match', () =>
      HttpResponse.json(
        { detail: 'Too many requests' },
        { status: 429, headers: { 'Retry-After': '900' } },
      ),
    ),
  )

  show()
  await choosePair()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Too many requests. Try again in 15 minutes.',
  )
})

test('a match without a language model configured says so', async () => {
  pickable()
  server.use(
    http.post('/api/resumes/:id/match', () =>
      HttpResponse.json({ detail: 'The language model is not configured' }, { status: 503 }),
    ),
  )

  show()
  await choosePair()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'The language model is not configured',
  )
})

test('the history lists past matches and opens one', async () => {
  server.use(
    http.get('/api/matches', () =>
      HttpResponse.json([
        {
          id: 'm1',
          document_id: 'd1',
          document_title: 'Python Developer — DCV',
          resume_id: 'r1',
          score: 0.75,
          matched_count: 2,
          missing_count: 1,
          created_at: '2026-09-07T12:00:00Z',
        },
      ]),
    ),
    http.get('/api/matches/m1', () => HttpResponse.json(MATCH)),
  )

  show('/matches')
  await userEvent.click(
    await screen.findByRole('link', { name: /75% · Python Developer — DCV/ }),
  )

  expect(await screen.findByRole('heading', { name: /75% match/ })).toBeInTheDocument()
})

test('an empty history says so rather than showing nothing', async () => {
  server.use(http.get('/api/matches', () => HttpResponse.json([])))

  show('/matches')

  expect(await screen.findByText('No matches yet.')).toBeInTheDocument()
})
