import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { MemoryRouter, Route, Routes, useParams } from 'react-router'
import { expect, test } from 'vitest'

import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { Interview } from './Interview'
import { Match } from './Match'

function resume(id: string, created: string, name: string) {
  return {
    id,
    content: 'Five years of Python.',
    target_role: 'Backend developer',
    original_filename: name,
    created_at: created,
  }
}

const POSTING = {
  id: 'd1',
  title: 'Python Developer — DCV',
  source_url: null,
  metadata: {},
  chunk_count: 3,
  created_at: '2026-09-07T11:00:00Z',
}

function Landed({ what }: { what: string }) {
  const params = useParams()

  return <p>{`${what} ${Object.values(params)[0] ?? ''}`}</p>
}

function show(at: '/match' | '/interview') {
  return render(
    <Providers client={createQueryClient()}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="/match" element={<Match />} />
          <Route path="/interview" element={<Interview />} />
          <Route path="/matches/:matchId" element={<Landed what="Match" />} />
          <Route path="/interviews/:sessionId" element={<Landed what="Interview" />} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  )
}

function pickable(): void {
  server.use(
    http.get('/api/resumes', () =>
      HttpResponse.json([
        resume('r-old', '2026-08-01T10:00:00Z', 'old.pdf'),
        resume('r-new', '2026-09-01T10:00:00Z', 'new.pdf'),
      ]),
    ),
    http.get('/api/documents', () => HttpResponse.json([POSTING])),
  )
}

async function choosePosting(): Promise<void> {
  // Waiting for the options, not for the selects: both render at once with
  // only their placeholder, and selecting fails on a value not yet arrived.
  await screen.findByRole('option', { name: /new\.pdf/ })
  await screen.findByRole('option', { name: 'Python Developer — DCV' })
  await userEvent.selectOptions(screen.getByLabelText('Job posting'), 'd1')
}

test('the newest resume is chosen until another is picked', async () => {
  pickable()

  show('/match')
  await screen.findByRole('option', { name: /new\.pdf/ })

  expect(screen.getByLabelText('Resume')).toHaveValue('r-new')
})

test('a match sends the chosen pair and opens the result', async () => {
  const sent: { resume: string; document: string }[] = []
  pickable()
  server.use(
    http.post('/api/resumes/:id/match', async ({ request, params }) => {
      const body = (await request.json()) as { document_id: string }
      sent.push({ resume: String(params.id), document: body.document_id })

      return HttpResponse.json({ id: 'm1' })
    }),
  )

  show('/match')
  await choosePosting()
  await userEvent.selectOptions(screen.getByLabelText('Resume'), 'r-old')
  await userEvent.click(screen.getByRole('button', { name: 'Match' }))

  expect(await screen.findByText('Match m1')).toBeInTheDocument()
  expect(sent).toEqual([{ resume: 'r-old', document: 'd1' }])
})

test('an interview starts on the chosen pair and opens it', async () => {
  const sent: unknown[] = []
  pickable()
  server.use(
    http.post('/api/sessions', async ({ request }) => {
      sent.push(await request.json())

      return HttpResponse.json({ id: 's1' }, { status: 201 })
    }),
  )

  show('/interview')
  await choosePosting()
  await userEvent.click(screen.getByRole('button', { name: 'Start the interview' }))

  expect(await screen.findByText('Interview s1')).toBeInTheDocument()
  expect(sent).toEqual([{ resume_id: 'r-new', document_id: 'd1' }])
})

test('the rate limit says how long to wait, not just that it was hit', async () => {
  pickable()
  server.use(
    http.post('/api/resumes/:id/match', () =>
      HttpResponse.json(
        { detail: 'Too many requests' },
        { status: 429, headers: { 'Retry-After': '900' } },
      ),
    ),
  )

  show('/match')
  await choosePosting()
  await userEvent.click(screen.getByRole('button', { name: 'Match' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Too many requests. Try again in 15 minutes.',
  )
})

test('a posting without requirements says why there is no interview', async () => {
  pickable()
  server.use(
    http.post('/api/sessions', () =>
      HttpResponse.json(
        { detail: 'This posting has no requirements to build interview questions from' },
        { status: 422 },
      ),
    ),
  )

  show('/interview')
  await choosePosting()
  await userEvent.click(screen.getByRole('button', { name: 'Start the interview' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('no requirements')
})

test('an empty knowledge base points at where to fix it', async () => {
  server.use(
    http.get('/api/resumes', () =>
      HttpResponse.json([resume('r1', '2026-09-01T10:00:00Z', 'cv.pdf')]),
    ),
    http.get('/api/documents', () => HttpResponse.json([])),
  )

  show('/match')

  expect(await screen.findByRole('link', { name: 'Add a job posting' })).toBeInTheDocument()
})

test('having no resumes points at where to fix that instead', async () => {
  server.use(
    http.get('/api/resumes', () => HttpResponse.json([])),
    http.get('/api/documents', () => HttpResponse.json([POSTING])),
  )

  show('/interview')

  expect(await screen.findByRole('link', { name: 'Add one' })).toBeInTheDocument()
  await waitFor(() => {
    expect(screen.getByRole('button', { name: 'Start the interview' })).toBeDisabled()
  })
})

test('the interview page links to the interviews in History', async () => {
  pickable()

  show('/interview')

  expect(await screen.findByRole('link', { name: 'Your past interviews' })).toHaveAttribute(
    'href',
    '/history?kind=interviews',
  )
})
