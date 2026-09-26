import { renderHook, waitFor } from '@testing-library/react'
import type { QueryClient } from '@tanstack/react-query'
import { HttpResponse, http } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, test } from 'vitest'

import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { dashboardKey, useDashboard } from './dashboard'
import { useDeleteDocument, useIngestText } from './documents'
import { useStartInterview } from './interview'
import { useMatch } from './matching'
import { useCreateResume } from './resumes'

const PAIRING = { resumeId: 'resume-1', documentId: 'document-1' }

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <Providers client={client}>{children}</Providers>
  }
}

describe('useDashboard', () => {
  test('reads the steps', async () => {
    const steps = [{ kind: 'add_resume' }, { kind: 'add_posting' }]
    server.use(http.get('/api/dashboard', () => HttpResponse.json({ steps })))

    const { result } = renderHook(() => useDashboard(), {
      wrapper: wrapperFor(createQueryClient()),
    })

    await waitFor(() => {
      expect(result.current.data).toEqual(steps)
    })
  })

  test('fails with the reason the API gave', async () => {
    server.use(
      http.get('/api/dashboard', () =>
        HttpResponse.json({ detail: 'Database unavailable' }, { status: 503 }),
      ),
    )

    const { result } = renderHook(() => useDashboard(), {
      wrapper: wrapperFor(createQueryClient()),
    })

    await waitFor(() => {
      expect(result.current.error?.message).toBe('Database unavailable')
    })
  })
})

/**
 * Each change the dashboard's steps are chosen from, and the request that
 * makes it. The answers are the least each hook needs to call it a success.
 */
const CHANGES = [
  {
    name: 'adding a resume',
    handler: http.post('/api/resumes', () => HttpResponse.json({ id: 'r' }, { status: 201 })),
    run: (client: QueryClient) =>
      renderHook(() => useCreateResume(), { wrapper: wrapperFor(client) }).result.current
        .mutateAsync({ content: 'Python', targetRole: '' }),
  },
  {
    name: 'adding a posting',
    handler: http.post('/api/documents', () => HttpResponse.json({ id: 'd' }, { status: 201 })),
    run: (client: QueryClient) =>
      renderHook(() => useIngestText(), { wrapper: wrapperFor(client) }).result.current
        .mutateAsync('A posting'),
  },
  {
    name: 'deleting a posting',
    handler: http.delete('/api/documents/:id', () => new HttpResponse(null, { status: 204 })),
    run: (client: QueryClient) =>
      renderHook(() => useDeleteDocument(), { wrapper: wrapperFor(client) }).result.current
        .mutateAsync('d'),
  },
  {
    name: 'matching',
    handler: http.post('/api/resumes/:id/match', () => HttpResponse.json({ id: 'm' })),
    run: (client: QueryClient) =>
      renderHook(() => useMatch(), { wrapper: wrapperFor(client) }).result.current
        .mutateAsync(PAIRING),
  },
  {
    name: 'starting an interview',
    handler: http.post('/api/sessions', () => HttpResponse.json({ id: 's' }, { status: 201 })),
    run: (client: QueryClient) =>
      renderHook(() => useStartInterview(), { wrapper: wrapperFor(client) }).result.current
        .mutateAsync(PAIRING),
  },
]

describe('the dashboard is read again after', () => {
  test.each(CHANGES)('$name', async ({ handler, run }) => {
    server.use(handler)
    const client = createQueryClient()
    client.setQueryData(dashboardKey, [{ kind: 'add_another_posting' }])

    await run(client)

    expect(client.getQueryState(dashboardKey)?.isInvalidated).toBe(true)
  })
})
