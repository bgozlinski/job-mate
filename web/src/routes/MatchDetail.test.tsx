import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { MemoryRouter, Route, Routes, useParams } from 'react-router'
import { expect, test } from 'vitest'

import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { MatchDetail } from './MatchDetail'

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

function Landed({ what }: { what: string }) {
  const params = useParams()

  return <p>{`${what} ${Object.values(params)[0] ?? ''}`}</p>
}

function show(match: object = MATCH) {
  server.use(http.get('/api/matches/m1', () => HttpResponse.json(match)))

  return render(
    <Providers client={createQueryClient()}>
      <MemoryRouter initialEntries={['/matches/m1']}>
        <Routes>
          <Route path="/matches/:matchId" element={<MatchDetail />} />
          <Route path="/documents/:documentId" element={<Landed what="Posting" />} />
          <Route path="/interviews/:sessionId" element={<Landed what="Interview" />} />
          <Route path="/history" element={<Landed what="History" />} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  )
}

test('a match reports the score the API computed', async () => {
  // The number is never worked out here: it is a coverage ratio computed in
  // Python so it can be reproduced and explained.
  show()

  expect(await screen.findByRole('heading', { name: /75% match/ })).toBeInTheDocument()
})

test('suggestions and notes stay two lists', async () => {
  // They come back separately on purpose: one is text to put in the resume,
  // the other is a remark about it. Merged, "the resume does not evidence
  // Kubernetes" reads as a bullet point to paste in.
  show()

  expect(
    await screen.findByRole('heading', { name: 'Suggested bullet points' }),
  ).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Notes on the resume' })).toBeInTheDocument()
})

test('a covered requirement shows what the model quoted for it', async () => {
  // Without the evidence a verdict has to be taken on trust; with it a
  // candidate can disagree.
  show()

  expect(await screen.findByText('Ten years of Python')).toBeInTheDocument()
})

test('the way back leads to the posting the match was run against', async () => {
  show()
  await userEvent.click(await screen.findByRole('link', { name: 'Python Developer — DCV' }))

  expect(await screen.findByText('Posting d1')).toBeInTheDocument()
})

test('with its posting deleted, the way back leads to History', async () => {
  // A match is a snapshot and outlives the posting it was run against.
  show({ ...MATCH, document_id: null })
  await screen.findByRole('heading', { name: /75% match/ })
  await userEvent.click(screen.getByRole('link', { name: 'History' }))

  expect(await screen.findByText(/^History/)).toBeInTheDocument()
})

test('practising starts an interview on the same pair and opens it', async () => {
  const sent: unknown[] = []
  server.use(
    http.post('/api/sessions', async ({ request }) => {
      sent.push(await request.json())

      return HttpResponse.json({ id: 's1' }, { status: 201 })
    }),
  )

  show()
  await userEvent.click(
    await screen.findByRole('button', { name: 'Practise interview' }),
  )

  expect(await screen.findByText('Interview s1')).toBeInTheDocument()
  expect(sent).toEqual([{ resume_id: 'r1', document_id: 'd1' }])
})

test('with its resume deleted there is nothing to practise on', async () => {
  show({ ...MATCH, resume_id: null })

  expect(
    await screen.findByRole('button', { name: 'Practise interview' }),
  ).toBeDisabled()
  expect(screen.getByText(/has been deleted/)).toBeInTheDocument()
})

test('a match that failed to load can be asked again', async () => {
  let calls = 0
  server.use(
    http.get('/api/matches/m1', () => {
      calls += 1

      return calls === 1
        ? HttpResponse.json({ detail: 'Could not read this match' }, { status: 500 })
        : HttpResponse.json(MATCH)
    }),
  )

  render(
    <Providers client={createQueryClient()}>
      <MemoryRouter initialEntries={['/matches/m1']}>
        <Routes>
          <Route path="/matches/:matchId" element={<MatchDetail />} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  )
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not read this match')
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(await screen.findByRole('heading', { name: /75% match/ })).toBeInTheDocument()
})
