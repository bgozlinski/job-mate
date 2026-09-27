import type { QueryClient } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { Link, MemoryRouter, Route, Routes, useLocation, useParams } from 'react-router'
import { expect, test } from 'vitest'

import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { Documents } from './Documents'
import { today } from '../time'
import type { Arrival } from './Posting'

const TITLE = 'Python Developer — DCV Technologies'

interface Stored {
  id: string
  title: string | null
  source_url: string | null
  company: string | null
  role: string | null
  city: string | null
  work_mode: 'remote' | 'hybrid' | 'office' | null
  posted_on: string | null
  applied_on: string | null
  applied_resume: {
    id: string
    original_filename: string | null
    target_role: string | null
    created_at: string
  } | null
  metadata: Record<string, unknown>
  chunk_count: number
  requirement_count: number | null
  created_at: string
  stage: number
  best_score: number | null
}

function posting(overrides: Partial<Stored> = {}): Stored {
  return {
    id: '01a0-posting',
    title: 'Python Developer — DCV Technologies',
    source_url: 'https://justjoin.it/job-offer/dcv-python',
    company: null,
    role: null,
    city: null,
    work_mode: null,
    posted_on: null,
    applied_on: null,
    applied_resume: null,
    metadata: { company: 'DCV Technologies' },
    chunk_count: 3,
    requirement_count: 6,
    created_at: '2026-09-07T12:00:00Z',
    stage: 1,
    best_score: null,
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

function show({ resumes = [RESUME] }: { resumes?: unknown[] } = {}): QueryClient {
  // The page reads the resumes to run Match and Practise from a row.
  server.use(http.get('/api/resumes', () => HttpResponse.json(resumes)))
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

/** The register's rows, header first, without the rows opened under an entry. */
async function registerRows(): Promise<HTMLElement[]> {
  const table = await screen.findByRole('table', { name: 'Postings' })

  return within(table)
    .getAllByRole('row')
    .filter((row) => within(row).queryAllByRole('cell').length !== 1)
}

/** One row of the register: 0 is the header. */
async function registerRow(index: number): Promise<HTMLElement> {
  const row = (await registerRows())[index]

  if (!row) {
    throw new Error(`The register has no row ${String(index)}`)
  }

  return row
}

test('the register names its eight columns, and actions', async () => {
  listing(posting())

  show()

  const header = await registerRow(0)
  expect(
    within(header)
      .getAllByRole('columnheader')
      .map((cell) => cell.textContent),
  ).toEqual([
    'Company',
    'Role',
    'Location',
    'Link',
    'Posted',
    'Added',
    'Applied',
    'Resume',
    'Actions',
  ])
})

test('a row carries company, role, a short link and its days', async () => {
  listing(
    posting({
      company: 'DCV Technologies',
      role: 'Python Developer',
      city: 'Warszawa',
      work_mode: 'remote',
      posted_on: '2026-09-05',
      applied_on: '2026-09-20',
      applied_resume: { ...RESUME, target_role: 'Backend' },
    }),
  )

  show()

  const row = await registerRow(1)
  const cells = within(row).getAllByRole('cell')
  expect(cells.map((cell) => cell.textContent).slice(0, 8)).toEqual([
    'DCV Technologies',
    expect.stringContaining('Python Developer'),
    'Warszawa, remote',
    'justjoin.it (opens in a new tab)',
    'Sep 5, 2026',
    expect.stringMatching(/2026/),
    'Sep 20, 2026',
    'cv.pdf',
  ])
  const link = within(row).getByRole('link', { name: /justjoin\.it/ })
  expect(link).toHaveAttribute('href', 'https://justjoin.it/job-offer/dcv-python')
  expect(link).toHaveAttribute('rel', 'noopener noreferrer')
})

test('without a company or role the row falls back to the title', async () => {
  listing(posting({ source_url: null }))

  show()

  const row = await registerRow(1)
  expect(within(row).getByRole('link', { name: TITLE })).toHaveAttribute(
    'href',
    '/documents/01a0-posting',
  )
  expect(row).toHaveTextContent('not stated')
  expect(row).toHaveTextContent('no link')
  expect(row).toHaveTextContent('not applied')
})

test('an application whose resume was deleted says so', async () => {
  listing(posting({ applied_on: '2026-09-20', applied_resume: null, stage: 4 }))

  show()

  const row = await registerRow(1)
  expect(row).toHaveTextContent('deleted resume')
  expect(row).toHaveTextContent('Stage 4 of 4: Applied')
})

test('each row says how far you got with the posting', async () => {
  listing(
    posting({ stage: 2, best_score: 0.72 }),
    posting({ id: 'd2', title: 'Untouched', requirement_count: null }),
  )

  show()

  const [, first, second] = await registerRows()
  expect(first).toHaveTextContent('Stage 2 of 4: Match')
  expect(first).toHaveTextContent('72%')
  expect(second).toHaveTextContent('Stage 1 of 4: Posting')
  expect(second).toHaveTextContent('requirements not read')
  expect(screen.queryByText(/chunks/)).not.toBeInTheDocument()
})

/** Record what the application routes are sent. */
function applications(): { method: string; body: unknown }[] {
  const sent: { method: string; body: unknown }[] = []
  server.use(
    http.put('/api/documents/:id/application', async ({ request }) => {
      sent.push({ method: 'PUT', body: await request.json() })

      return HttpResponse.json(posting())
    }),
    http.delete('/api/documents/:id/application', () => {
      sent.push({ method: 'DELETE', body: null })

      return new HttpResponse(null, { status: 204 })
    }),
  )

  return sent
}

test('marking as applied sends today where you are and the main resume', async () => {
  const sent = applications()
  listing(posting())

  show({
    resumes: [
      { ...RESUME, id: 'r-old', created_at: '2026-08-01T10:00:00Z' },
      { ...RESUME, id: 'r-new', created_at: '2026-09-01T10:00:00Z' },
    ],
  })
  await userEvent.click(
    await screen.findByRole('button', { name: `Mark ${TITLE} as applied` }),
  )
  const form = await screen.findByRole('form', { name: `Application to ${TITLE}` })
  expect(within(form).getByLabelText('With resume')).toHaveValue('r-new')
  expect(within(form).getByLabelText('Applied on')).toHaveValue(today())
  await userEvent.click(within(form).getByRole('button', { name: 'Save' }))

  await waitFor(() => {
    expect(sent).toEqual([
      { method: 'PUT', body: { applied_on: today(), resume_id: 'r-new' } },
    ])
  })
  await waitFor(() => {
    expect(
      screen.queryByRole('form', { name: `Application to ${TITLE}` }),
    ).not.toBeInTheDocument()
  })
})

test('an application can be taken back from its stamp', async () => {
  const sent = applications()
  listing(
    posting({ applied_on: '2026-09-20', applied_resume: { ...RESUME, target_role: null } }),
  )

  show()
  await userEvent.click(
    await screen.findByRole('button', {
      name: `Applied Sep 20, 2026: change the application to ${TITLE}`,
    }),
  )
  await userEvent.click(
    await screen.findByRole('button', { name: 'Not applied after all' }),
  )

  await waitFor(() => {
    expect(sent).toEqual([{ method: 'DELETE', body: null }])
  })
})

test('without a resume there is nothing to apply with', async () => {
  listing(posting())

  show({ resumes: [] })
  await userEvent.click(
    await screen.findByRole('button', { name: `Mark ${TITLE} as applied` }),
  )

  expect(
    await screen.findByText(/An application names the resume you sent/),
  ).toBeInTheDocument()
  expect(
    screen.queryByRole('form', { name: `Application to ${TITLE}` }),
  ).not.toBeInTheDocument()
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
  await screen.findByRole('link', { name: TITLE })
  expect(screen.queryByLabelText('Job posting URL')).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: 'Add posting' }))

  expect(screen.getByLabelText('Job posting URL')).toBeInTheDocument()
})

test('no postings says so and leads to adding the first posting', async () => {
  listing()

  show()
  expect(await screen.findByText('No postings yet.')).toBeInTheDocument()
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

test('the postings show their shape while they load', async () => {
  server.use(
    http.get('/api/documents', async () => {
      await delay(50)

      return HttpResponse.json([posting()])
    }),
  )

  show()

  expect(screen.getByRole('status')).toHaveTextContent('Loading your postings…')
  expect(await screen.findByRole('link', { name: TITLE })).toBeInTheDocument()
})

test('postings that failed to load can be asked for again', async () => {
  let calls = 0
  server.use(
    http.get('/api/documents', () => {
      calls += 1

      return calls === 1
        ? HttpResponse.json({ detail: 'Could not read your postings' }, { status: 500 })
        : HttpResponse.json([posting()])
    }),
  )

  show()
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not read your postings')
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(await screen.findByRole('link', { name: TITLE })).toBeInTheDocument()
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
    await screen.findByRole('link', { name: 'Python Developer — DCV Technologies' }),
  ).toBeInTheDocument()
})

const SEARCH = 'https://justjoin.it/job-offers/all-locations/python?experience-levels=junior'
const OFFER = (slug: string) => `https://justjoin.it/job-offer/${slug}`

/**
 * Answer the search with these new addresses, and each from-url with the
 * status given for its slug. Returns the addresses from-url was asked for.
 */
function searchable(
  search: { new: string[]; known: number } | { status: number; detail: string },
  answers: Record<string, { status: number; detail?: string }> = {},
): string[] {
  const asked: string[] = []
  server.use(
    http.post('/api/documents/from-search', () =>
      'status' in search
        ? HttpResponse.json({ detail: search.detail }, { status: search.status })
        : HttpResponse.json(search),
    ),
    http.post('/api/documents/from-url', async ({ request }) => {
      const { url } = (await request.json()) as { url: string }
      asked.push(url)
      const answer = answers[url.split('/').pop() ?? ''] ?? { status: 201 }

      return answer.status < 300
        ? HttpResponse.json(posting({ id: url }), { status: answer.status })
        : HttpResponse.json({ detail: answer.detail }, { status: answer.status })
    }),
  )

  return asked
}

async function importSearch(): Promise<void> {
  await userEvent.click(await screen.findByText('…or import a whole search'))
  await userEvent.type(screen.getByLabelText('Search results URL'), SEARCH)
  await userEvent.click(screen.getByRole('button', { name: 'Import new postings' }))
}

test('importing a search adds each new posting in turn and counts them', async () => {
  listing()
  const asked = searchable({ new: [OFFER('a'), OFFER('b')], known: 1 })

  show()
  await importSearch()

  expect(await screen.findByRole('status')).toHaveTextContent(
    'Added 2 new postings; 1 was already here.',
  )
  expect(asked).toEqual([OFFER('a'), OFFER('b')])
})

test('a search with nothing new adds nothing and says so', async () => {
  listing()
  const asked = searchable({ new: [], known: 3 })

  show()
  await importSearch()

  expect(await screen.findByRole('status')).toHaveTextContent(
    'Nothing new: all 3 postings listed are already here.',
  )
  expect(asked).toEqual([])
})

test('a posting that fails is named and the rest are still added', async () => {
  listing()
  searchable(
    { new: [OFFER('broken'), OFFER('fine')], known: 0 },
    { broken: { status: 422, detail: 'The page carries no job posting' } },
  )

  show()
  await importSearch()

  expect(await screen.findByRole('status')).toHaveTextContent('Added 1 new posting.')
  expect(screen.getByRole('alert')).toHaveTextContent(
    'broken: The page carries no job posting',
  )
})

test('a spent limit stops the import and says how many are left', async () => {
  listing()
  const asked = searchable(
    { new: [OFFER('a'), OFFER('b'), OFFER('c')], known: 0 },
    { b: { status: 429, detail: 'Too many requests' } },
  )

  show()
  await importSearch()

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Too many requests. 2 left: import the same search again later to add them.',
  )
  expect(asked).toEqual([OFFER('a'), OFFER('b')])
})

test('a page that is not a search says why, in the API’s words', async () => {
  listing()
  const asked = searchable({ status: 422, detail: 'The page lists no job offers' })

  show()
  await importSearch()

  expect(await screen.findByRole('alert')).toHaveTextContent('The page lists no job offers')
  expect(asked).toEqual([])
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

test('deleting asks first and sends nothing until confirmed', async () => {
  const deleted = deletable(204)

  show()
  await userEvent.click(await screen.findByRole('button', { name: `Delete ${TITLE}` }))

  const confirm = screen.getByRole('group', { name: `Confirm deleting ${TITLE}` })
  expect(confirm).toHaveTextContent('for good')
  expect(deleted).toEqual([])
})

test('cancelling goes back without sending anything', async () => {
  const deleted = deletable(204)

  show()
  await userEvent.click(await screen.findByRole('button', { name: `Delete ${TITLE}` }))
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

  expect(screen.getByRole('button', { name: `Delete ${TITLE}` })).toBeInTheDocument()
  expect(deleted).toEqual([])
})

test('a confirmed delete removes the posting and says so', async () => {
  const deleted = deletable(204)

  show()
  await userEvent.click(await screen.findByRole('button', { name: `Delete ${TITLE}` }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete for good' }))

  expect(await screen.findByText('No postings yet.')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent(`Posting deleted: ${TITLE}.`)
  expect(deleted).toEqual(['01a0-posting'])
})

test('a failure says why and keeps the posting', async () => {
  deletable(500, 'The database is unavailable')

  show()
  await userEvent.click(await screen.findByRole('button', { name: `Delete ${TITLE}` }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete for good' }))

  expect(await screen.findByRole('alert')).toHaveTextContent('The database is unavailable')
  expect(screen.getByRole('link', { name: TITLE })).toBeInTheDocument()
})

test('a posting somebody else already deleted is simply gone', async () => {
  deletable(404)

  show()
  await userEvent.click(await screen.findByRole('button', { name: `Delete ${TITLE}` }))
  await userEvent.click(screen.getByRole('button', { name: 'Delete for good' }))

  expect(await screen.findByText('No postings yet.')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).toBeNull()
})
