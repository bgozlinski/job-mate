import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { MemoryRouter, Route, Routes, useParams } from 'react-router'
import { expect, test } from 'vitest'

import type { Step } from '../api/dashboard'
import type { InterviewSummary } from '../api/interview'
import type { MatchSummary } from '../api/matching'
import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { Dashboard } from './Dashboard'

const CONTINUE: Step = {
  kind: 'continue_interview',
  session_id: 's1',
  document_id: 'd1',
  document_title: 'Python Developer at Acme',
  answered: 3,
  question_count: 6,
}
const MATCH: Step = {
  kind: 'match',
  document_id: 'd2',
  document_title: 'Data Engineer at Foo',
  resume_id: 'r1',
}
const PRACTISE: Step = {
  kind: 'practise',
  document_id: 'd3',
  document_title: 'Backend Engineer at Bar',
  resume_id: 'r2',
  score: 0.72,
}

const A_MATCH: MatchSummary = {
  id: 'm1',
  document_id: 'd3',
  document_title: 'Backend Engineer at Bar',
  resume_id: 'r2',
  score: 0.72,
  matched_count: 5,
  missing_count: 2,
  created_at: '2026-09-25T10:00:00Z',
}
const AN_INTERVIEW: InterviewSummary = {
  id: 's1',
  resume_id: 'r1',
  document_id: 'd1',
  document_title: 'Python Developer at Acme',
  status: 'active',
  score: null,
  question_count: 6,
  created_at: '2026-09-26T10:00:00Z',
  finished_at: null,
}

/** Where an action lands, so a test can see it went there. */
function Landed({ what }: { what: string }) {
  const params = useParams()

  return <p>{`${what} ${String(Object.values(params)[0])}`}</p>
}

function arrange(
  steps: Step[],
  { matches = [], interviews = [] }: { matches?: MatchSummary[]; interviews?: InterviewSummary[] } = {},
): void {
  server.use(
    http.get('/api/dashboard', () => HttpResponse.json({ steps })),
    http.get('/api/matches', () => HttpResponse.json(matches)),
    http.get('/api/sessions', () => HttpResponse.json(interviews)),
  )
}

function show() {
  return render(
    <Providers client={createQueryClient()}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/matches/:matchId" element={<Landed what="Match" />} />
          <Route path="/interviews/:sessionId" element={<Landed what="Interview" />} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  )
}

const ADD_RESUME: Step = { kind: 'add_resume' }
const ADD_POSTING: Step = { kind: 'add_posting' }
const UP_TO_DATE: Step = { kind: 'add_another_posting' }

test.each([
  {
    step: ADD_RESUME,
    sentence: 'Add your resume',
    link: 'Add resume',
    href: '/resumes',
  },
  {
    step: ADD_POSTING,
    sentence: 'Add a job posting',
    link: 'Add posting',
    href: '/documents',
  },
  {
    step: UP_TO_DATE,
    sentence: "You're up to date",
    link: 'Add posting',
    href: '/documents',
  },
  {
    step: CONTINUE,
    sentence: 'Finish your interview for Python Developer at Acme',
    link: 'Continue your interview for Python Developer at Acme',
    href: '/interviews/s1',
  },
])('the next step "$sentence" links where it is done', async ({ step, sentence, link, href }) => {
  arrange([step])
  show()

  expect(await screen.findByRole('heading', { level: 2, name: sentence })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: link })).toHaveAttribute('href', href)
})

test('an unfinished interview says how far it got', async () => {
  arrange([CONTINUE])
  show()

  expect(await screen.findByText('3 of 6 questions answered.')).toBeInTheDocument()
})

test('a match step offers to match on the spot', async () => {
  arrange([MATCH])
  show()

  expect(
    await screen.findByRole('heading', { level: 2, name: 'See how your resume fits Data Engineer at Foo' }),
  ).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Match my resume with Data Engineer at Foo' })).toBeEnabled()
})

test('a practice step says how well the resume matched', async () => {
  arrange([PRACTISE])
  show()

  expect(
    await screen.findByRole('heading', { level: 2, name: 'Practise for Backend Engineer at Bar' }),
  ).toBeInTheDocument()
  expect(screen.getByText('Your resume matched 72%.')).toBeInTheDocument()
})

test('a posting without a title is still named', async () => {
  arrange([{ ...MATCH, document_title: null }])
  show()

  expect(
    await screen.findByRole('heading', { level: 2, name: 'See how your resume fits an untitled posting' }),
  ).toBeInTheDocument()
})

test('starting an interview uses the resume and posting of the step, then opens it', async () => {
  let sent: unknown
  server.use(
    http.post('/api/sessions', async ({ request }) => {
      sent = await request.json()

      return HttpResponse.json({ id: 's9' }, { status: 201 })
    }),
  )
  arrange([PRACTISE])
  show()

  await userEvent.click(
    await screen.findByRole('button', { name: 'Start interview for Backend Engineer at Bar' }),
  )

  expect(await screen.findByText('Interview s9')).toBeInTheDocument()
  expect(sent).toEqual({ resume_id: 'r2', document_id: 'd3' })
})

test('matching opens the result', async () => {
  server.use(http.post('/api/resumes/r1/match', () => HttpResponse.json({ id: 'm9' })))
  arrange([MATCH])
  show()

  await userEvent.click(
    await screen.findByRole('button', { name: 'Match my resume with Data Engineer at Foo' }),
  )

  expect(await screen.findByText('Match m9')).toBeInTheDocument()
})

test('while one step waits on the model, no other action can start', async () => {
  server.use(
    http.post('/api/resumes/r1/match', async () => {
      await delay('infinite')

      return HttpResponse.json({ id: 'never' })
    }),
  )
  arrange([MATCH, PRACTISE])
  show()

  await userEvent.click(
    await screen.findByRole('button', { name: 'Match my resume with Data Engineer at Foo' }),
  )

  expect(await screen.findByRole('status')).toHaveTextContent('Matching your resume…')
  expect(screen.getByRole('button', { name: 'Match my resume with Data Engineer at Foo' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Start interview for Backend Engineer at Bar' })).toBeDisabled()
})

test('a failed action is reported beside its step', async () => {
  server.use(
    http.post('/api/sessions', () =>
      HttpResponse.json({ detail: 'This posting has no requirements yet' }, { status: 422 }),
    ),
  )
  arrange([MATCH, PRACTISE])
  show()

  await userEvent.click(
    await screen.findByRole('button', { name: 'Start interview for Backend Engineer at Bar' }),
  )

  const others = screen.getByRole('region', { name: 'Other things to do' })
  expect(await within(others).findByRole('alert')).toHaveTextContent(
    'This posting has no requirements yet',
  )
})

test('the other steps are listed under the next one', async () => {
  arrange([CONTINUE, MATCH, PRACTISE])
  show()

  const others = await screen.findByRole('region', { name: 'Other things to do' })
  expect(within(others).getByText('See how your resume fits Data Engineer at Foo')).toBeInTheDocument()
  expect(within(others).getByText('Practise for Backend Engineer at Bar')).toBeInTheDocument()
})

test('with one step there is nothing else to list', async () => {
  arrange([MATCH])
  show()

  await screen.findByRole('heading', { level: 2 })
  expect(screen.queryByRole('region', { name: 'Other things to do' })).not.toBeInTheDocument()
})

test('recent work is listed newest first, with the way to the rest', async () => {
  arrange([MATCH], { matches: [A_MATCH], interviews: [AN_INTERVIEW] })
  show()

  const recently = await screen.findByRole('region', { name: 'Recently' })
  const rows = within(within(recently).getByRole('list')).getAllByRole('link')
  expect(rows.map((link) => link.getAttribute('href'))).toEqual([
    '/interviews/s1',
    '/matches/m1',
  ])
  expect(within(recently).getByRole('link', { name: 'See all history' })).toHaveAttribute(
    'href',
    '/history',
  )
})

test('an account with no history has no recent section', async () => {
  arrange([MATCH])
  show()

  await screen.findByRole('heading', { level: 2 })
  await waitFor(() => {
    expect(screen.queryByRole('region', { name: 'Recently' })).not.toBeInTheDocument()
  })
})

test('loading shows a skeleton, then the step', async () => {
  arrange([MATCH])
  show()

  expect(screen.getByText('Working out what to do next…')).toBeInTheDocument()
  expect(await screen.findByRole('heading', { level: 2 })).toBeInTheDocument()
})

test('a failed read can be tried again', async () => {
  let failing = true
  server.use(
    http.get('/api/dashboard', () =>
      failing
        ? HttpResponse.json({ detail: 'Database unavailable' }, { status: 503 })
        : HttpResponse.json({ steps: [MATCH] }),
    ),
    http.get('/api/matches', () => HttpResponse.json([])),
    http.get('/api/sessions', () => HttpResponse.json([])),
  )
  show()

  expect(await screen.findByRole('alert')).toHaveTextContent('Database unavailable')
  failing = false
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(
    await screen.findByRole('heading', { level: 2, name: 'See how your resume fits Data Engineer at Foo' }),
  ).toBeInTheDocument()
})
