import { render, screen, waitFor, within } from '@testing-library/react'
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

interface Stored { id: string; created_at: string }

/**
 * Answer GET /history the way the API does: both kinds merged newest first,
 * narrowed by kind, one page cut from the union, with the count of all.
 */
function answer(matches: Stored[], interviews: Stored[]): string[] {
  const asked: string[] = []
  server.use(
    http.get('/api/history', ({ request }) => {
      const params = new URL(request.url).searchParams
      const kind = params.get('kind') ?? 'all'
      const limit = Number(params.get('limit'))
      const offset = Number(params.get('offset'))
      asked.push(`${kind}:${String(limit)}@${String(offset)}`)
      const timeline = [
        ...(kind === 'interviews' ? [] : matches.map((m) => ({ kind: 'match', match: m, at: m.created_at }))),
        ...(kind === 'matches' ? [] : interviews.map((i) => ({ kind: 'interview', interview: i, at: i.created_at }))),
      ].sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : 0))

      return HttpResponse.json({
        items: timeline
          .slice(offset, offset + limit)
          .map((entry) => ({ kind: entry.kind, match: 'match' in entry ? entry.match : null, interview: 'interview' in entry ? entry.interview : null })),
        total: timeline.length,
      })
    }),
  )

  return asked
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
    'Match 56% — Python Developer — DCV',
    'Interview 50% — Python Developer — DCV',
    'Match 56% — Python Developer — DCV',
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
      name: 'Interview in progress — Python Developer — DCV',
    }),
  ).toBeInTheDocument()
  expect(
    screen.getByRole('link', {
      name: 'Interview finished, nothing judged — Python Developer — DCV',
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
    await screen.findByRole('link', { name: 'Match 56% — Deleted posting' }),
  ).toBeInTheDocument()
})

test('a long history is numbered in pages kept in the address', async () => {
  const many = Array.from({ length: 45 }, (_, i) =>
    match(`m${String(i)}`, `2026-09-${String(10 + (i % 18)).padStart(2, '0')}T12:00:00Z`),
  )
  const asked = answer(many, [])

  show('/history?kind=matches&page=2')

  const pages = await screen.findByRole('navigation', { name: 'Pages of history' })
  expect(within(pages).getByText('Page 2').closest('[aria-current="page"]')).not.toBeNull()
  expect(within(pages).getByRole('link', { name: 'Page 3' })).toHaveAttribute(
    'href',
    '/history?kind=matches&page=3',
  )
  expect(asked).toEqual(['matches:20@20'])
})

test('picking a kind starts at its first page', async () => {
  const asked = answer(
    Array.from({ length: 30 }, (_, i) => match(`m${String(i)}`, '2026-09-22T12:00:00Z')),
    [interview('s1', '2026-09-21T12:00:00Z')],
  )

  show('/history?page=2')
  await screen.findByRole('navigation', { name: 'Pages of history' })
  await userEvent.click(screen.getByRole('button', { name: 'Interviews' }))

  await waitFor(() => {
    expect(asked).toEqual(['all:20@20', 'interviews:20@0'])
  })
})

test('a history that failed to load can be asked again', async () => {
  let calls = 0
  server.use(
    http.get('/api/history', () => {
      calls += 1

      return calls === 1
        ? HttpResponse.json({ detail: 'Could not read your history' }, { status: 500 })
        : HttpResponse.json({
            items: [{ kind: 'match', match: match('m1', '2026-09-22T12:00:00Z') }],
            total: 1,
          })
    }),
  )

  show()
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not read your history')
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(await screen.findByRole('link', { name: /^Match 56% —/ })).toBeInTheDocument()
})
