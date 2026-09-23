import type { QueryClient } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'

import { sessionKey } from '../auth/session'
import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { Documents } from './Documents'

interface Stored {
  id: string
  title: string | null
  source_url: string | null
  metadata: Record<string, unknown>
  chunk_count: number
  created_at: string
}

function posting(overrides: Partial<Stored> = {}): Stored {
  return {
    id: '01a0-posting',
    title: 'Python Developer — DCV Technologies',
    source_url: 'https://justjoin.it/job-offer/dcv-python',
    metadata: { company: 'DCV Technologies' },
    chunk_count: 3,
    created_at: '2026-09-07T12:00:00Z',
    ...overrides,
  }
}

function show({ admin = false }: { admin?: boolean } = {}): QueryClient {
  // The page reads the session to decide whether to offer deleting (FR-6).
  server.use(
    http.get('/api/auth/me', () =>
      HttpResponse.json({
        id: '01a0-user',
        email: 'reader@example.com',
        is_admin: admin,
        created_at: '2026-09-01T12:00:00Z',
      }),
    ),
  )
  const client = createQueryClient()

  render(
    <Providers client={client}>
      <MemoryRouter>
        <Documents />
      </MemoryRouter>
    </Providers>,
  )

  return client
}

function listing(...postings: Stored[]): void {
  server.use(http.get('/api/documents', () => HttpResponse.json(postings)))
}

test('the knowledge base is listed', async () => {
  listing(posting())

  show()

  expect(
    await screen.findByRole('heading', { name: 'Python Developer — DCV Technologies' }),
  ).toBeInTheDocument()
  expect(screen.getByText('3 chunks')).toBeInTheDocument()
})

test('an empty knowledge base says so rather than showing nothing', async () => {
  listing()

  show()

  expect(await screen.findByText('Nothing in the knowledge base yet.')).toBeInTheDocument()
})

test('a posting with no chunks is called out', async () => {
  // It is in the database and invisible to retrieval, which a zero in a
  // caption does not convey.
  listing(posting({ chunk_count: 0 }))

  show()

  expect(await screen.findByRole('alert')).toHaveTextContent('No chunks')
})

test('a posting is read from its address', async () => {
  const asked: string[] = []
  listing()
  server.use(
    http.post('/api/documents/from-url', async ({ request }) => {
      const body = (await request.json()) as { url: string }
      asked.push(body.url)

      return HttpResponse.json(posting(), { status: 201 })
    }),
  )

  show()
  await userEvent.type(
    await screen.findByLabelText('Job posting URL'),
    'https://justjoin.it/job-offer/dcv-python',
  )
  await userEvent.click(screen.getByRole('button', { name: 'Read the posting' }))

  expect(await screen.findByRole('status')).toHaveTextContent('Stored as 01a0-posting')
  expect(asked).toEqual(['https://justjoin.it/job-offer/dcv-python'])
})

test('a posting already in the base is reported as such, not as a failure', async () => {
  // 200 rather than 201 is deduplication working (FR-1). Showing it as an
  // error would turn a feature into a fault; showing it as a plain success
  // would hide that nothing new was stored.
  listing()
  server.use(
    http.post('/api/documents/from-url', () => HttpResponse.json(posting(), { status: 200 })),
  )

  show()
  await userEvent.type(
    await screen.findByLabelText('Job posting URL'),
    'https://justjoin.it/job-offer/dcv-python',
  )
  await userEvent.click(screen.getByRole('button', { name: 'Read the posting' }))

  expect(await screen.findByRole('status')).toHaveTextContent(
    'Already in the knowledge base',
  )
})

test('a refused address says why, in the API’s own words', async () => {
  // The allowlist is a policy decision (NFR-5) and the API's message names
  // the host it refused. Replacing it with "something went wrong" would leave
  // the user guessing at a rule they cannot see.
  listing()
  server.use(
    http.post('/api/documents/from-url', () =>
      HttpResponse.json(
        { detail: 'www.linkedin.com is not a site this application reads' },
        { status: 422 },
      ),
    ),
  )

  show()
  await userEvent.type(
    await screen.findByLabelText('Job posting URL'),
    'https://www.linkedin.com/jobs/view/1',
  )
  await userEvent.click(screen.getByRole('button', { name: 'Read the posting' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'www.linkedin.com is not a site this application reads',
  )
})

test('a stored posting appears in the listing without a reload', async () => {
  let stored = false
  server.use(
    http.get('/api/documents', () => HttpResponse.json(stored ? [posting()] : [])),
    http.post('/api/documents/from-url', () => {
      stored = true

      return HttpResponse.json(posting(), { status: 201 })
    }),
  )

  show()
  await userEvent.type(await screen.findByLabelText('Job posting URL'), 'https://x.test/1')
  await userEvent.click(screen.getByRole('button', { name: 'Read the posting' }))

  expect(
    await screen.findByRole('heading', { name: 'Python Developer — DCV Technologies' }),
  ).toBeInTheDocument()
})

test('a file is sent as multipart with the browser’s own boundary', async () => {
  // No Content-Type is set anywhere in the client: the browser writes it
  // together with the multipart boundary, and a header set by hand loses the
  // boundary and the upload arrives unparseable.
  const seen: { type: string | null; body: string }[] = []
  listing()
  server.use(
    http.post('/api/documents/upload', async ({ request }) => {
      // Read as text rather than through request.formData(). The body is
      // built by jsdom and parsed by Node's undici, and their File classes
      // are different objects: undici's multipart parser rejects jsdom's File
      // outright. That is a mismatch between two test-environment libraries,
      // not something a browser or the API ever sees, and the raw body shows
      // what was sent just as well.
      seen.push({
        type: request.headers.get('content-type'),
        body: await request.text(),
      })

      return HttpResponse.json(posting(), { status: 201 })
    }),
  )

  show()
  await userEvent.click(await screen.findByText('…or upload a file'))
  await userEvent.upload(
    screen.getByLabelText('Job posting file (PDF, DOCX or text)'),
    new File(['a posting'], 'offer.txt', { type: 'text/plain' }),
  )
  await userEvent.click(screen.getByRole('button', { name: 'Upload' }))

  await waitFor(() => {
    expect(seen).toHaveLength(1)
  })
  expect(seen[0]?.type).toMatch(/^multipart\/form-data; boundary=/)
  expect(seen[0]?.body).toContain('name="file"')
  // Not asserted here: the filename and the bytes. jsdom builds the File and
  // Node's undici serialises the FormData, and undici does not recognise
  // jsdom's File, so the part arrives as filename="blob" with no content --
  // in this environment only. A browser has one implementation of both and
  // sends the real name, which matters because the API stores it as the
  // document's title. That half is covered against the running API instead.

})

test('pasted text longer than the API accepts is refused before it is sent', async () => {
  // The limit is enforced by the API too; checking here saves a request that
  // can only be rejected, and says which limit was passed.
  listing()

  show()
  await userEvent.click(await screen.findByText('…or paste the text'))
  // Pasted rather than typed: 200 001 keystrokes would take minutes, and what
  // is under test is the state the text puts the form into.
  await userEvent.click(screen.getByLabelText('Job posting text'))
  await userEvent.paste('x'.repeat(200_001))

  expect(await screen.findByRole('alert')).toHaveTextContent('longer than 200,000')
  expect(screen.getByRole('button', { name: 'Store' })).toBeDisabled()
})

const TITLE = 'Python Developer — DCV Technologies'

/** A listing that forgets the posting once a DELETE answers `status`. */
function deletable(status: number, detail?: string): string[] {
  const deleted: string[] = []
  let postings = [posting()]
  server.use(
    http.get('/api/documents', () => HttpResponse.json(postings)),
    http.delete('/api/documents/:id', ({ params }) => {
      deleted.push(String(params.id))

      if (status === 204) {
        postings = []

        return new HttpResponse(null, { status: 204 })
      }

      if (status === 404) {
        postings = []
      }

      return HttpResponse.json({ detail: detail ?? 'Not found' }, { status })
    }),
  )

  return deleted
}

test('someone who is not an administrator is not offered deleting', async () => {
  listing(posting())

  const client = show()

  await screen.findByRole('heading', { name: TITLE })
  await waitFor(() => {
    expect(client.getQueryState(sessionKey)?.status).toBe('success')
  })

  expect(screen.queryByRole('button', { name: `Delete ${TITLE}` })).toBeNull()
})

test('deleting asks first and sends nothing until confirmed', async () => {
  const deleted = deletable(204)

  show({ admin: true })
  await userEvent.click(await screen.findByRole('button', { name: `Delete ${TITLE}` }))

  const confirm = screen.getByRole('group', { name: `Confirm deleting ${TITLE}` })
  expect(confirm).toHaveTextContent('for good')
  expect(deleted).toEqual([])
})

test('cancelling goes back without sending anything', async () => {
  const deleted = deletable(204)

  show({ admin: true })
  await userEvent.click(await screen.findByRole('button', { name: `Delete ${TITLE}` }))
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

  expect(screen.getByRole('button', { name: `Delete ${TITLE}` })).toBeInTheDocument()
  expect(deleted).toEqual([])
})

test('a confirmed delete removes the posting from the listing', async () => {
  const deleted = deletable(204)

  show({ admin: true })
  await userEvent.click(await screen.findByRole('button', { name: `Delete ${TITLE}` }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete for good' }))

  expect(await screen.findByText('Nothing in the knowledge base yet.')).toBeInTheDocument()
  expect(deleted).toEqual(['01a0-posting'])
})

test('a refusal says why and keeps the posting', async () => {
  // Rights revoked after the page read the session: the API has the last word.
  deletable(403, 'Administrator access required')

  show({ admin: true })
  await userEvent.click(await screen.findByRole('button', { name: `Delete ${TITLE}` }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete for good' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('Administrator access required')
  expect(screen.getByRole('heading', { name: TITLE })).toBeInTheDocument()
})

test('a posting somebody else already deleted is simply gone', async () => {
  deletable(404)

  show({ admin: true })
  await userEvent.click(await screen.findByRole('button', { name: `Delete ${TITLE}` }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete for good' }))

  expect(await screen.findByText('Nothing in the knowledge base yet.')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).toBeNull()
})
