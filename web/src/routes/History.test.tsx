import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { expect, test } from 'vitest'

import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { History } from './History'

function match(id: string, at: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    document_id: 'd1',
    document_title: 'Python Developer — DCV',
    resume_id: 'r1',
    score: 0.56,
    matched_count: 5,
    missing_count: 4,
    created_at: at,
    ...overrides,
  }
}

function interview(id: string, at: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    resume_id: 'r1',
    document_id: 'd1',
    document_title: 'Python Developer — DCV',
    status: 'finished',
    score: 0.5,
    question_count: 5,
    created_at: at,
    finished_at: at,
    ...overrides,
  }
}

function show(at = '/history') {
  return render(
    <Providers client={createQueryClient()}>
      <MemoryRouter initialEntries={[at]}>
        <Routes>
          <Route path="/history" element={<History />} />
          <Route path="/matches/:matchId" element={<p>A match</p>} />
          <Route path="/interviews/:sessionId" element={<p>An interview</p>} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  )
}

function answer(matches: unknown[], interviews: unknown[]): void {
  server.use(
    http.get('/api/matches', () => HttpResponse.json(matches)),
    http.get('/api/sessions', () => HttpResponse.json(interviews)),
  )
}

function rowNames(): string[] {
  return screen
    .getAllByRole('link')
    .map((link) => link.textContent)
}

test('matches and interviews share one timeline, newest first', async () => {
  answer(
    [match('m-old', '2026-09-10T12:00:00Z'), match('m-new', '2026-09-22T12:00:00Z')],
    [interview('s-mid', '2026-09-15T12:00:00Z')],
  )

  show()
  await screen.findAllByRole('link')

  expect(rowNames()).toEqual([
    'Match · 56% · Python Developer — DCV',
    'Interview · 50% · Python Developer — DCV',
    'Match · 56% · Python Developer — DCV',
  ])
  expect(screen.getAllByRole('link')[0]).toHaveAttribute('href', '/matches/m-new')
})

test('an interview in progress and one never judged say so', async () => {
  answer(
    [],
    [
      interview('s1', '2026-09-20T12:00:00Z', { status: 'active', score: null }),
      interview('s2', '2026-09-19T12:00:00Z', { score: null }),
    ],
  )

  show()

  expect(
    await screen.findByRole('link', {
      name: 'Interview · In progress · Python Developer — DCV',
    }),
  ).toBeInTheDocument()
  expect(
    screen.getByRole('link', {
      name: 'Interview · Finished, nothing judged · Python Developer — DCV',
    }),
  ).toBeInTheDocument()
})

test('the filter narrows the timeline and lives in the address', async () => {
  answer(
    [match('m1', '2026-09-22T12:00:00Z')],
    [interview('s1', '2026-09-21T12:00:00Z')],
  )

  show('/history?kind=interviews')

  expect(
    await screen.findByRole('link', { name: /^Interview/ }),
  ).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /^Match/ })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Interviews' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )

  await userEvent.click(screen.getByRole('button', { name: 'All' }))

  expect(await screen.findByRole('link', { name: /^Match/ })).toBeInTheDocument()
})

test('an empty history says so and points at the postings', async () => {
  answer([], [])

  show()

  expect(await screen.findByText('Nothing here yet.')).toBeInTheDocument()
})

test('a deleted posting is named as deleted, not left blank', async () => {
  answer([match('m1', '2026-09-22T12:00:00Z', { document_title: null })], [])

  show()

  expect(
    await screen.findByRole('link', { name: 'Match · 56% · Deleted posting' }),
  ).toBeInTheDocument()
})

test('loading more asks both lists for more, from the top', async () => {
  const asked: string[] = []
  const page = (url: string, make: (index: number) => unknown) => {
    const params = new URL(url).searchParams
    asked.push(`${new URL(url).pathname}:${params.get('limit') ?? ''}@${params.get('offset') ?? ''}`)

    return HttpResponse.json(
      Array.from({ length: Number(params.get('limit')) }, (_, index) => make(index)),
    )
  }
  server.use(
    http.get('/api/matches', ({ request }) =>
      page(request.url, (i) => match(`m${String(i)}`, '2026-09-22T12:00:00Z')),
    ),
    http.get('/api/sessions', ({ request }) =>
      page(request.url, (i) => interview(`s${String(i)}`, '2026-09-21T12:00:00Z')),
    ),
  )

  show()
  await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))

  await waitFor(() => {
    expect(asked.sort()).toEqual([
      '/api/matches:20@0',
      '/api/matches:40@0',
      '/api/sessions:20@0',
      '/api/sessions:40@0',
    ])
  })
})

test('a history that failed to load can be asked again', async () => {
  let calls = 0
  server.use(
    http.get('/api/matches', () => {
      calls += 1

      return calls === 1
        ? HttpResponse.json({ detail: 'Could not read your match history' }, { status: 500 })
        : HttpResponse.json([match('m1', '2026-09-22T12:00:00Z')])
    }),
    http.get('/api/sessions', () => HttpResponse.json([])),
  )

  show()
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not read your match history')
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(await screen.findByRole('link', { name: /^Match · 56%/ })).toBeInTheDocument()
})
