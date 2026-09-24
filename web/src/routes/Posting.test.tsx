import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { MemoryRouter, Route, Routes, useParams } from 'react-router'
import { expect, test } from 'vitest'

import type { DocumentDetail } from '../api/documents'
import type { Resume } from '../api/resumes'
import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { Posting, newest } from './Posting'

const POSTING: DocumentDetail = {
  id: 'd1',
  title: 'Python Developer — DCV',
  source_url: 'https://justjoin.it/job-offer/dcv-python',
  metadata: {},
  chunk_count: 3,
  created_at: '2026-09-10T12:00:00Z',
  content: 'We are looking for a Python developer to join our backend team.',
  requirements: ['python', 'docker'],
}

function resume(id: string, created: string, name: string): Resume {
  return {
    id,
    content: 'Five years of Python.',
    target_role: null,
    skills: null,
    original_filename: name,
    mime_type: null,
    created_at: created,
  } as Resume
}

const OLD_CV = resume('r-old', '2026-08-01T10:00:00Z', 'old.pdf')
const NEW_CV = resume('r-new', '2026-09-01T10:00:00Z', 'new.pdf')

/** Where an action lands, so a test can see it went there. */
function Landed({ what }: { what: string }) {
  const params = useParams()

  return <p>{`${what} ${String(Object.values(params)[0])}`}</p>
}

function show(state?: unknown) {
  return render(
    <Providers client={createQueryClient()}>
      <MemoryRouter initialEntries={[{ pathname: '/documents/d1', state }]}>
        <Routes>
          <Route path="/documents/:documentId" element={<Posting />} />
          <Route path="/matches/:matchId" element={<Landed what="Match" />} />
          <Route path="/interviews/:sessionId" element={<Landed what="Interview" />} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  )
}

function arrange({
  posting = POSTING,
  resumes = [OLD_CV, NEW_CV],
  matches = [] as unknown[],
  interviews = [] as unknown[],
}: {
  posting?: DocumentDetail
  resumes?: Resume[]
  matches?: unknown[]
  interviews?: unknown[]
} = {}): void {
  server.use(
    http.get('/api/documents/d1', () => HttpResponse.json(posting)),
    http.get('/api/resumes', () => HttpResponse.json(resumes)),
    http.get('/api/matches', () => HttpResponse.json(matches)),
    http.get('/api/sessions', () => HttpResponse.json(interviews)),
  )
}

test('the newest resume is the one used unless another is picked', () => {
  expect(newest([OLD_CV, NEW_CV])?.id).toBe('r-new')
  expect(newest([NEW_CV, OLD_CV])?.id).toBe('r-new')
  expect(newest([])).toBeUndefined()
})

test('the page shows the posting, what it asks for and where it came from', async () => {
  arrange()

  show()

  expect(
    await screen.findByRole('heading', { name: 'Python Developer — DCV' }),
  ).toBeInTheDocument()
  expect(screen.getByText('python')).toBeInTheDocument()
  expect(screen.getByText('docker')).toBeInTheDocument()
  expect(screen.getByText(/looking for a Python developer/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'justjoin.it' })).toHaveAttribute(
    'href',
    POSTING.source_url,
  )
})

test('matching uses the newest resume and opens the result', async () => {
  const sent: { resume: string; document: string }[] = []
  arrange()
  server.use(
    http.post('/api/resumes/:id/match', async ({ request, params }) => {
      const body = (await request.json()) as { document_id: string }
      sent.push({ resume: String(params.id), document: body.document_id })

      return HttpResponse.json({ id: 'm1' })
    }),
  )

  show()
  await userEvent.click(await screen.findByRole('button', { name: 'Match my CV' }))

  expect(await screen.findByText('Match m1')).toBeInTheDocument()
  expect(sent).toEqual([{ resume: 'r-new', document: 'd1' }])
})

test('another resume can be picked for the action', async () => {
  const sent: string[] = []
  arrange()
  server.use(
    http.post('/api/resumes/:id/match', ({ params }) => {
      sent.push(String(params.id))

      return HttpResponse.json({ id: 'm1' })
    }),
  )

  show()
  await screen.findByRole('option', { name: 'old.pdf' })
  await userEvent.selectOptions(screen.getByLabelText('Resume'), 'r-old')
  await userEvent.click(screen.getByRole('button', { name: 'Match my CV' }))

  await waitFor(() => {
    expect(sent).toEqual(['r-old'])
  })
})

test('practising starts an interview on the pair and opens it', async () => {
  const sent: unknown[] = []
  arrange()
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
  expect(sent).toEqual([{ resume_id: 'r-new', document_id: 'd1' }])
})

test('without a resume both actions wait, and say where to add one', async () => {
  arrange({ resumes: [] })

  show()

  expect(await screen.findByRole('link', { name: 'Add a resume first' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Match my CV' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Practise interview' })).toBeDisabled()
})

test('a posting nobody read cannot be interviewed on, but can be matched', async () => {
  // The API refuses an interview without requirements (422); matching has a
  // keyword fallback and still works.
  arrange({ posting: { ...POSTING, requirements: null } })

  show()
  // The actions wait for the resumes, so wait for them too.
  await screen.findByRole('option', { name: 'new.pdf' })

  expect(screen.getByText(/have not been read yet/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Practise interview' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Match my CV' })).toBeEnabled()
})

test('the rate limit says how long to wait', async () => {
  arrange()
  server.use(
    http.post('/api/resumes/:id/match', () =>
      HttpResponse.json(
        { detail: 'Too many requests' },
        { status: 429, headers: { 'Retry-After': '1200' } },
      ),
    ),
  )

  show()
  await userEvent.click(await screen.findByRole('button', { name: 'Match my CV' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Too many requests. Try again in 20 minutes.',
  )
})

test('no language model is reported in the API’s words', async () => {
  arrange()
  server.use(
    http.post('/api/sessions', () =>
      HttpResponse.json({ detail: 'The language model is not configured' }, { status: 503 }),
    ),
  )

  show()
  await userEvent.click(
    await screen.findByRole('button', { name: 'Practise interview' }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'The language model is not configured',
  )
})

test('your matches and interviews on this posting are listed', async () => {
  arrange({
    matches: [
      {
        id: 'm1',
        document_id: 'd1',
        document_title: 'Python Developer — DCV',
        resume_id: 'r-new',
        score: 0.56,
        matched_count: 5,
        missing_count: 4,
        created_at: '2026-09-12T12:00:00Z',
      },
    ],
    interviews: [
      {
        id: 's1',
        resume_id: 'r-new',
        document_id: 'd1',
        document_title: 'Python Developer — DCV',
        status: 'active',
        score: null,
        question_count: 5,
        created_at: '2026-09-20T12:00:00Z',
        finished_at: null,
      },
    ],
  })

  show()

  expect(await screen.findByRole('link', { name: '56%' })).toHaveAttribute(
    'href',
    '/matches/m1',
  )
  expect(screen.getByRole('link', { name: 'Continue' })).toHaveAttribute(
    'href',
    '/interviews/s1',
  )
})

test('the lists ask for this posting only', async () => {
  const asked: string[] = []
  arrange()
  server.use(
    http.get('/api/matches', ({ request }) => {
      asked.push(new URL(request.url).searchParams.get('document_id') ?? '')

      return HttpResponse.json([])
    }),
    http.get('/api/sessions', ({ request }) => {
      asked.push(new URL(request.url).searchParams.get('document_id') ?? '')

      return HttpResponse.json([])
    }),
  )

  show()

  expect(await screen.findByText('No matches yet.')).toBeInTheDocument()
  expect(await screen.findByText('No interviews yet.')).toBeInTheDocument()
  expect(asked).toEqual(['d1', 'd1'])
})

test('a posting that was already in the base says nothing new was stored', async () => {
  arrange()

  show({ duplicate: true })

  expect(
    await screen.findByText(/already in the knowledge base, so nothing new was stored/),
  ).toBeInTheDocument()
})

test('an unknown posting says so', async () => {
  server.use(
    http.get('/api/documents/d1', () =>
      HttpResponse.json({ detail: 'Not found' }, { status: 404 }),
    ),
  )

  show()

  expect(await screen.findByRole('alert')).toHaveTextContent('Not found')
  expect(screen.getByRole('link', { name: 'All postings' })).toBeInTheDocument()
})
