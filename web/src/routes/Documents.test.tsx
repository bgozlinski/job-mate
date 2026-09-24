import type { QueryClient } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { Link, MemoryRouter, Route, Routes, useLocation, useParams } from 'react-router'
import { expect, test } from 'vitest'

import { sessionKey } from '../auth/session'
import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { Documents } from './Documents'
import type { Arrival } from './Posting'

const TITLE = 'Python Developer — DCV Technologies'

interface Stored {
  id: string
  title: string | null
  source_url: string | null
  metadata: Record<string, unknown>
  chunk_count: number
  requirement_count: number | null
  created_at: string
}

function posting(overrides: Partial<Stored> = {}): Stored {
  return {
    id: '01a0-posting',
    title: 'Python Developer — DCV Technologies',
    source_url: 'https://justjoin.it/job-offer/dcv-python',
    metadata: { company: 'DCV Technologies' },
    chunk_count: 3,
    requirement_count: 6,
    created_at: '2026-09-07T12:00:00Z',
    ...overrides,
  }
}

const RESUME = {
  id: 'r1',
  content: 'Ten years of Python.',
  target_role: null,
  original_filename: 'cv.pdf',
  created_at: '2026-09-01T10:00:00Z',
}

function show({
  admin = false,
  resumes = [RESUME],
}: { admin?: boolean; resumes?: unknown[] } = {}): QueryClient {
  // The page reads the session to decide whether to offer deleting (FR-6),
  // and the resumes to run Match and Practise from a row.
  server.use(
    http.get('/api/auth/me', () =>
      HttpResponse.json({
        id: '01a0-user',
        email: 'reader@example.com',
        is_admin: admin,
        created_at: '2026-09-01T12:00:00Z',
      }),
    ),
    http.get('/api/resumes', () => HttpResponse.json(resumes)),
  )
  const client = createQueryClient()

  render(
    <Providers client={client}>
      <MemoryRouter initialEntries={['/documents']}>
        <Routes>
          <Route path="/documents" element={<Documents />} />
          <Route path="/documents/:documentId" element={<Opened />} />
          <Route path="/matches/:id" element={<Landed what="Match" />} />
          <Route path="/interviews/:id" element={<Landed what="Interview" />} />
        </Routes>
      </MemoryRouter>
    </Providers>,
  )

  return client
}

function Landed({ what }: { what: string }) {
  const { id } = useParams()

  return <p>{`${what} ${id ?? ''}`}</p>
}

/**
 * Stands in for the posting's page: it says which posting was opened and
 * whether the ingestion reported it as already there. The page itself has
 * its own tests.
 */
function Opened() {
  const { documentId } = useParams()
  const arrival = useLocation().state as Arrival | null

  return (
    <>
      <p>
        Opened {documentId}
        {arrival?.duplicate ? ' (already there)' : ''}
      </p>
      <Link to="/documents">Back</Link>
    </>
  )
}

function listing(...postings: Stored[]): void {
  server.use(http.get('/api/documents', () => HttpResponse.json(postings)))
}

test('each posting is a row saying where it came from and whether it was read', async () => {
  listing(posting(), posting({ id: 'd2', title: 'Unread', requirement_count: null }))

  show()

  expect(await screen.findByRole('heading', { name: TITLE })).toBeInTheDocument()
  // The source's domain rather than the whole address, and requirements
  // rather than chunks: what matters when choosing an offer.
  // The line is split by its <time>, so it is matched as a whole paragraph.
  const line = (pattern: RegExp) => (_: string, element: Element | null) =>
    element?.tagName === 'P' && pattern.test(element.textContent)
  expect(screen.getByText(line(/^justjoin\.it · .+ · 6 requirements$/))).toBeInTheDocument()
  expect(screen.getByText(line(/requirements not read$/))).toBeInTheDocument()
  expect(screen.queryByText(/chunks/)).not.toBeInTheDocument()
})

test('matching from a row uses the newest resume and opens the result', async () => {
  const sent: { resume: string; document: string }[] = []
  listing(posting())
  server.use(
    http.post('/api/resumes/:id/match', async ({ request, params }) => {
      const body = (await request.json()) as { document_id: string }
      sent.push({ resume: String(params.id), document: body.document_id })

      return HttpResponse.json({ id: 'm1' })
    }),
  )

  show({
    resumes: [
      { ...RESUME, id: 'r-old', created_at: '2026-08-01T10:00:00Z' },
      { ...RESUME, id: 'r-new', created_at: '2026-09-01T10:00:00Z' },
    ],
  })
  const matchButton = await screen.findByRole('button', {
    name: `Match my CV with ${TITLE}`,
  })
  await waitFor(() => {
    expect(matchButton).toBeEnabled()
  })
  await userEvent.click(matchButton)

  expect(await screen.findByText('Match m1')).toBeInTheDocument()
  expect(sent).toEqual([{ resume: 'r-new', document: '01a0-posting' }])
})

test('practising from a row starts an interview on the pair', async () => {
  const sent: unknown[] = []
  listing(posting())
  server.use(
    http.post('/api/sessions', async ({ request }) => {
      sent.push(await request.json())
      await delay(30)

      return HttpResponse.json({ id: 's1' }, { status: 201 })
    }),
  )

  show()
  const practise = await screen.findByRole('button', {
    name: `Practise an interview for ${TITLE}`,
  })
  await waitFor(() => {
    expect(practise).toBeEnabled()
  })
  await userEvent.click(practise)

  expect(await screen.findByText('Preparing questions…')).toBeInTheDocument()
  expect(await screen.findByText('Interview s1')).toBeInTheDocument()
  expect(sent).toEqual([{ resume_id: 'r1', document_id: '01a0-posting' }])
})

test('a posting nobody read cannot be practised on from its row', async () => {
  listing(posting({ requirement_count: null }))

  show()

  const practise = await screen.findByRole('button', {
    name: `Practise an interview for ${TITLE}`,
  })
  await waitFor(() => {
    expect(
      screen.getByRole('button', { name: `Match my CV with ${TITLE}` }),
    ).toBeEnabled()
  })
  expect(practise).toBeDisabled()
})

test('without a resume the rows wait and say where to add one', async () => {
  listing(posting())

  show({ resumes: [] })

  expect(await screen.findByRole('link', { name: 'Add a resume first' })).toBeInTheDocument()
  expect(
    screen.getByRole('button', { name: `Match my CV with ${TITLE}` }),
  ).toBeDisabled()
})

test('adding sits behind a button while there are postings to list', async () => {
  listing(posting())

  show()
  await screen.findByRole('heading', { name: TITLE })
  expect(screen.queryByLabelText('Job posting URL')).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Add posting' }))

  expect(screen.getByLabelText('Job posting URL')).toBeInTheDocument()
})

test('an empty knowledge base says so and leads to adding the first posting', async () => {
  listing()

  show()
  expect(await screen.findByText('The knowledge base is empty.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Add the first posting' }))

  expect(screen.getByLabelText('Job posting URL')).toHaveFocus()
})

test('a posting with no chunks is called out as a notice, not an error', async () => {
  // It is in the database and invisible to retrieval, which a zero in a
  // caption does not convey -- but nothing failed, so it is not red.
  listing(posting({ chunk_count: 0 }))

  show()

  expect(await screen.findByText(/No chunks/)).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('the knowledge base shows its shape while it loads', async () => {
  server.use(
    http.get('/api/documents', async () => {
      await delay(50)

      return HttpResponse.json([posting()])
    }),
  )

  show()

  expect(screen.getByRole('status')).toHaveTextContent('Loading the knowledge base…')
  expect(await screen.findByRole('heading', { name: TITLE })).toBeInTheDocument()
})

test('a knowledge base that failed to load can be asked again', async () => {
  let calls = 0
  server.use(
    http.get('/api/documents', () => {
      calls += 1

      return calls === 1
        ? HttpResponse.json({ detail: 'Could not read the knowledge base' }, { status: 500 })
        : HttpResponse.json([posting()])
    }),
  )

  show()
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not read the knowledge base')
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(await screen.findByRole('heading', { name: TITLE })).toBeInTheDocument()
})

test('reading a posting says so while it takes', async () => {
  listing()
  server.use(
    http.post('/api/documents/from-url', async () => {
      await delay(50)

      return HttpResponse.json(posting(), { status: 201 })
    }),
  )

  show()
  await userEvent.type(await screen.findByLabelText('Job posting URL'), 'https://x.test/1')
  await userEvent.click(screen.getByRole('button', { name: 'Read the posting' }))

  expect(await screen.findByText('Reading the posting…')).toBeInTheDocument()
  expect(await screen.findByText('Opened 01a0-posting')).toBeInTheDocument()
})

test('a posting is read from its address and then opened', async () => {
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

  // Opened rather than reported: matching a CV against it happens on its page.
  expect(await screen.findByText('Opened 01a0-posting')).toBeInTheDocument()
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

  // The existing posting is opened, and told it was already there so its page
  // can say that nothing new was stored.
  expect(
    await screen.findByText('Opened 01a0-posting (already there)'),
  ).toBeInTheDocument()
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

test('a stored posting is in the listing on the way back, without a reload', async () => {
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
  await userEvent.click(await screen.findByRole('link', { name: 'Back' }))

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

test('a confirmed delete removes the posting and says so', async () => {
  const deleted = deletable(204)

  show({ admin: true })
  await userEvent.click(await screen.findByRole('button', { name: `Delete ${TITLE}` }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete for good' }))

  expect(await screen.findByText('The knowledge base is empty.')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent(`Posting deleted: ${TITLE}.`)
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

  expect(await screen.findByText('The knowledge base is empty.')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).toBeNull()
})
