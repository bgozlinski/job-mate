import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { expect, test } from 'vitest'

import type { Interview as InterviewData, InterviewMessage } from '../api/interview'
import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { Interview } from './Interview'
import { InterviewHistory } from './InterviewHistory'
import { InterviewSession } from './InterviewSession'

const RESUME = {
  id: 'r1',
  content: 'Five years of Python.',
  target_role: 'Backend developer',
  original_filename: 'cv.pdf',
  created_at: '2026-09-24T10:00:00Z',
}

const POSTING = {
  id: 'd1',
  title: 'Python Developer — DCV',
  source_url: null,
  metadata: {},
  chunk_count: 3,
  created_at: '2026-09-24T11:00:00Z',
}

function message(
  id: string,
  position: number,
  role: InterviewMessage['role'],
  content: string,
  extra: Partial<InterviewMessage> = {},
): InterviewMessage {
  return {
    id,
    position,
    role,
    content,
    requirement: 'Docker',
    verdicts: null,
    score: null,
    retrieved_chunk_ids: [],
    created_at: '2026-09-24T12:00:00Z',
    ...extra,
  }
}

const FIRST_QUESTION = message('q1', 0, 'interviewer', 'How did you use Docker?')

const STARTED: InterviewData = {
  id: 's1',
  resume_id: 'r1',
  document_id: 'd1',
  document_title: 'Python Developer — DCV',
  status: 'active',
  score: null,
  question_count: 2,
  created_at: '2026-09-24T12:00:00Z',
  finished_at: null,
  summary: null,
  messages: [FIRST_QUESTION],
}

const ANSWERED: InterviewData = {
  ...STARTED,
  messages: [
    FIRST_QUESTION,
    message('a1', 1, 'candidate', 'I containerised our API.'),
    message('e1', 2, 'evaluator', 'Say what the image size was before and after.', {
      score: 0.667,
      verdicts: {
        on_topic: { met: true, reason: 'It is about Docker.' },
        concrete_example: { met: true, reason: 'Names the API.' },
        consistent_with_resume: { met: false, reason: 'The resume never mentions Docker.' },
      },
    }),
    message('q2', 3, 'interviewer', 'Tell me about a Python service you ran.', {
      requirement: 'Python',
    }),
  ],
}

const FINISHED: InterviewData = {
  ...ANSWERED,
  status: 'finished',
  score: 0.667,
  finished_at: '2026-09-24T12:30:00Z',
  summary: {
    strengths: ['Docker'],
    improvements: [],
  },
  messages: ANSWERED.messages.slice(0, 3),
}

function show(at = '/interview') {
  return render(
    <Providers client={createQueryClient()}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="/interview" element={<Interview />} />
          <Route path="/interviews" element={<InterviewHistory />} />
          <Route path="/interviews/:sessionId" element={<InterviewSession />} />
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

function stored(interview: InterviewData): void {
  server.use(http.get('/api/sessions/s1', () => HttpResponse.json(interview)))
}

async function choosePair(): Promise<void> {
  await screen.findByRole('option', { name: /cv\.pdf/ })
  await screen.findByRole('option', { name: 'Python Developer — DCV' })

  await userEvent.selectOptions(screen.getByLabelText('Resume'), 'r1')
  await userEvent.selectOptions(screen.getByLabelText('Job posting'), 'd1')
  await userEvent.click(screen.getByRole('button', { name: 'Start the interview' }))
}

async function type(answer: string): Promise<void> {
  await userEvent.type(await screen.findByLabelText('Your answer'), answer)
  await userEvent.click(screen.getByRole('button', { name: 'Send answer' }))
}

test('starting an interview opens it on the first question', async () => {
  const sent: unknown[] = []
  pickable()
  server.use(
    http.post('/api/sessions', async ({ request }) => {
      sent.push(await request.json())

      return HttpResponse.json(STARTED, { status: 201 })
    }),
  )

  show()
  await choosePair()

  expect(await screen.findByText('How did you use Docker?')).toBeInTheDocument()
  expect(screen.getByText('Question 1 of 2')).toBeInTheDocument()
  expect(sent).toEqual([{ resume_id: 'r1', document_id: 'd1' }])
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

  show()
  await choosePair()

  expect(await screen.findByRole('alert')).toHaveTextContent('no requirements')
})

test('the rate limit says how long to wait', async () => {
  pickable()
  server.use(
    http.post('/api/sessions', () =>
      HttpResponse.json(
        { detail: 'Too many requests' },
        { status: 429, headers: { 'Retry-After': '600' } },
      ),
    ),
  )

  show()
  await choosePair()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Too many requests. Try again in 10 minutes.',
  )
})

test('having no resumes points at where to fix it', async () => {
  server.use(
    http.get('/api/resumes', () => HttpResponse.json([])),
    http.get('/api/documents', () => HttpResponse.json([POSTING])),
  )

  show()

  expect(await screen.findByRole('link', { name: 'Add one' })).toBeInTheDocument()
})

test('an answer comes back judged, with the reasons and the next question', async () => {
  const sent: unknown[] = []
  stored(STARTED)
  server.use(
    http.post('/api/sessions/s1/answers', async ({ request }) => {
      sent.push(await request.json())

      return HttpResponse.json(ANSWERED)
    }),
  )

  show('/interviews/s1')
  await type('I containerised our API.')

  const evaluation = await screen.findByRole('region', {
    name: 'Evaluation of your answer on Docker',
  })
  expect(within(evaluation).getByText('67%')).toBeInTheDocument()
  expect(within(evaluation).getByText('The resume never mentions Docker.')).toBeInTheDocument()
  expect(within(evaluation).getByText(/image size was before and after/)).toBeInTheDocument()
  expect(screen.getByText('Tell me about a Python service you ran.')).toBeInTheDocument()
  expect(screen.getByText('Question 2 of 2')).toBeInTheDocument()
  expect(screen.getByLabelText('Your answer')).toHaveValue('')
  // The answer names the question it answers, so a second copy of it is
  // refused instead of being taken as the answer to question two.
  expect(sent).toEqual([{ question_id: 'q1', content: 'I containerised our API.' }])
})

test('a failed answer keeps what was typed', async () => {
  // Nothing is saved when the model fails; the person sends again, and should
  // not have to type the answer a second time to do it.
  stored(STARTED)
  server.use(
    http.post('/api/sessions/s1/answers', () =>
      HttpResponse.json(
        { detail: 'The language model could not answer; nothing was saved, try again' },
        { status: 502 },
      ),
    ),
  )

  show('/interviews/s1')
  await type('I containerised our API.')

  expect(await screen.findByRole('alert')).toHaveTextContent('nothing was saved')
  expect(screen.getByLabelText('Your answer')).toHaveValue('I containerised our API.')
})

test('an answer that lost a race shows where the session is now', async () => {
  let reads = 0
  server.use(
    http.get('/api/sessions/s1', () => {
      reads += 1

      return HttpResponse.json(reads === 1 ? STARTED : ANSWERED)
    }),
    http.post('/api/sessions/s1/answers', () =>
      HttpResponse.json(
        { detail: 'That question has already been answered' },
        { status: 409 },
      ),
    ),
  )

  show('/interviews/s1')
  await type('I containerised our API.')

  expect(await screen.findByRole('alert')).toHaveTextContent('already been answered')
  expect(
    await screen.findByText('Tell me about a Python service you ran.'),
  ).toBeInTheDocument()
})

test('finishing early shows the summary and takes no more answers', async () => {
  stored(STARTED)
  server.use(
    http.post('/api/sessions/s1/finish', () =>
      HttpResponse.json({
        ...STARTED,
        status: 'finished',
        summary: { strengths: [], improvements: [] },
        finished_at: '2026-09-24T12:05:00Z',
      }),
    ),
  )

  show('/interviews/s1')
  await userEvent.click(
    await screen.findByRole('button', { name: 'Finish the interview' }),
  )

  expect(
    await screen.findByText('No answer was judged, so there is nothing to sum up.'),
  ).toBeInTheDocument()
  expect(screen.queryByLabelText('Your answer')).not.toBeInTheDocument()
})

test('a finished interview reads back with its summary', async () => {
  stored(FINISHED)

  show('/interviews/s1')

  expect(
    await screen.findByRole('heading', { name: /67% of the rubric met overall/ }),
  ).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Strong answers' })).toBeInTheDocument()
  expect(screen.queryByLabelText('Your answer')).not.toBeInTheDocument()
})

function row(overrides: Record<string, unknown>) {
  return {
    id: 's1',
    resume_id: 'r1',
    document_id: 'd1',
    document_title: 'Python Developer — DCV',
    status: 'active',
    score: null,
    question_count: 2,
    created_at: '2026-09-24T12:00:00Z',
    finished_at: null,
    ...overrides,
  }
}

test('the history lists your interviews and opens one where it stopped', async () => {
  server.use(
    http.get('/api/sessions', () =>
      HttpResponse.json([
        row({ id: 's1' }),
        row({
          id: 's0',
          document_title: 'Data Engineer',
          status: 'finished',
          score: 0.5,
          finished_at: '2026-09-23T12:00:00Z',
        }),
      ]),
    ),
  )
  stored(STARTED)

  show('/interviews')

  expect(
    await screen.findByRole('link', { name: '50% · Data Engineer' }),
  ).toBeInTheDocument()
  await userEvent.click(
    screen.getByRole('link', { name: 'In progress · Python Developer — DCV' }),
  )

  expect(await screen.findByText('How did you use Docker?')).toBeInTheDocument()
  expect(screen.getByLabelText('Your answer')).toBeInTheDocument()
})

test('an interview finished before any answer says nothing was judged', async () => {
  server.use(
    http.get('/api/sessions', () =>
      HttpResponse.json([row({ status: 'finished', finished_at: '2026-09-24T12:01:00Z' })]),
    ),
  )

  show('/interviews')

  expect(
    await screen.findByRole('link', {
      name: 'Finished, nothing judged · Python Developer — DCV',
    }),
  ).toBeInTheDocument()
})

test('an empty history says so rather than showing nothing', async () => {
  server.use(http.get('/api/sessions', () => HttpResponse.json([])))

  show('/interviews')

  expect(await screen.findByText('No interviews yet.')).toBeInTheDocument()
})

test('the history pages from the top with a growing limit', async () => {
  const limits: string[] = []
  server.use(
    http.get('/api/sessions', ({ request }) => {
      const url = new URL(request.url)
      limits.push(`${url.searchParams.get('limit') ?? ''}@${url.searchParams.get('offset') ?? ''}`)

      return HttpResponse.json(
        Array.from({ length: Number(url.searchParams.get('limit')) }, (_, index) =>
          row({ id: `s${String(index)}` }),
        ),
      )
    }),
  )

  show('/interviews')
  await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))

  await waitFor(() => {
    expect(limits).toEqual(['20@0', '40@0'])
  })
})

test('an interview that is not yours reads as not found', async () => {
  server.use(
    http.get('/api/sessions/s1', () =>
      HttpResponse.json({ detail: 'Interview not found' }, { status: 404 }),
    ),
  )

  show('/interviews/s1')

  expect(await screen.findByRole('alert')).toHaveTextContent('Interview not found')
})
