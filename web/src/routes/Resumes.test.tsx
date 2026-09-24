import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { MemoryRouter } from 'react-router'
import { beforeEach, expect, test, vi } from 'vitest'

import { saveFile } from '../api/download'
import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { Resumes } from './Resumes'

// jsdom implements neither URL.createObjectURL nor navigation, so the step
// that hands bytes to the browser is replaced; what it receives is the test.
vi.mock('../api/download', () => ({ saveFile: vi.fn() }))

beforeEach(() => {
  vi.mocked(saveFile).mockClear()
})

interface Stored {
  id: string
  content: string
  target_role: string | null
  original_filename: string | null
  created_at: string
}

function resume(overrides: Partial<Stored> = {}): Stored {
  return {
    id: '01a0-resume',
    content: 'Ten years of Python and Postgres.',
    target_role: 'Backend developer',
    original_filename: 'cv.pdf',
    created_at: '2026-09-07T12:00:00Z',
    ...overrides,
  }
}

function show() {
  return render(
    <Providers client={createQueryClient()}>
      <MemoryRouter>
        <Resumes />
      </MemoryRouter>
    </Providers>,
  )
}

function listing(...resumes: Stored[]): void {
  server.use(http.get('/api/resumes', () => HttpResponse.json(resumes)))
}

test('the caller’s resumes are listed', async () => {
  listing(resume())

  show()

  expect(await screen.findByRole('heading', { name: 'cv.pdf' })).toBeInTheDocument()
  expect(screen.getByText('Backend developer')).toBeInTheDocument()
})

test('a pasted resume is named for what it is, not left blank', async () => {
  listing(resume({ original_filename: null, target_role: null }))

  show()

  expect(await screen.findByRole('heading', { name: 'Pasted text' })).toBeInTheDocument()
  expect(screen.getByText('no target role')).toBeInTheDocument()
})

test('the text is behind a click, not drawn for every row', async () => {
  // A resume can be a hundred thousand characters; three of them rendered in
  // full is a page that crawls.
  listing(resume())

  show()

  const shown = await screen.findByText('Show text')
  expect(shown.closest('details')).not.toHaveAttribute('open')
})

test('an empty list says so and leads to adding the first resume', async () => {
  listing()

  show()
  expect(await screen.findByText('No resumes yet.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Add your first resume' }))

  expect(screen.getByLabelText('Resume file (PDF, DOCX or text)')).toHaveFocus()
})

test('the list shows its shape while it loads', async () => {
  server.use(
    http.get('/api/resumes', async () => {
      await delay(50)

      return HttpResponse.json([resume()])
    }),
  )

  show()

  expect(screen.getByRole('status')).toHaveTextContent('Loading your resumes…')
  expect(await screen.findByRole('heading', { name: 'cv.pdf' })).toBeInTheDocument()
})

test('a list that failed to load can be asked again', async () => {
  let calls = 0
  server.use(
    http.get('/api/resumes', () => {
      calls += 1

      return calls === 1
        ? HttpResponse.json({ detail: 'Could not read your resumes' }, { status: 500 })
        : HttpResponse.json([resume()])
    }),
  )

  show()
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not read your resumes')
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(await screen.findByRole('heading', { name: 'cv.pdf' })).toBeInTheDocument()
})

test('a pasted resume is stored with its target role', async () => {
  const sent: { content: string; target_role: string | null }[] = []
  listing()
  server.use(
    http.post('/api/resumes', async ({ request }) => {
      sent.push((await request.json()) as { content: string; target_role: string | null })

      return HttpResponse.json(resume(), { status: 201 })
    }),
  )

  show()
  await userEvent.click(await screen.findByText('…or paste the text'))
  const pasting = within(screen.getByRole('form', { name: 'Paste a resume' }))
  await userEvent.type(pasting.getByLabelText('Resume text'), 'Ten years of Python.')
  await userEvent.type(pasting.getByLabelText('Target role (optional)'), 'Backend')
  await userEvent.click(pasting.getByRole('button', { name: 'Save' }))

  await waitFor(() => {
    expect(sent).toHaveLength(1)
  })
  expect(sent[0]?.content).toBe('Ten years of Python.')
  expect(sent[0]?.target_role).toBe('Backend')
})

test('an empty target role is sent as nothing, not as an empty string', async () => {
  // The column is nullable, and "" is a value: it would show as a resume
  // targeting a role with no name.
  const sent: { target_role: string | null }[] = []
  listing()
  server.use(
    http.post('/api/resumes', async ({ request }) => {
      sent.push((await request.json()) as { target_role: string | null })

      return HttpResponse.json(resume(), { status: 201 })
    }),
  )

  show()
  await userEvent.click(await screen.findByText('…or paste the text'))
  await userEvent.type(screen.getByLabelText('Resume text'), 'Ten years of Python.')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() => {
    expect(sent).toHaveLength(1)
  })
  expect(sent[0]?.target_role).toBeNull()
})

test('a stored resume appears in the list without a reload', async () => {
  let stored = false
  server.use(
    http.get('/api/resumes', () => HttpResponse.json(stored ? [resume()] : [])),
    http.post('/api/resumes', () => {
      stored = true

      return HttpResponse.json(resume(), { status: 201 })
    }),
  )

  show()
  await userEvent.click(await screen.findByText('…or paste the text'))
  await userEvent.type(screen.getByLabelText('Resume text'), 'Ten years of Python.')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))

  expect(await screen.findByRole('heading', { name: 'cv.pdf' })).toBeInTheDocument()
})

test('a resume file is sent as multipart', async () => {
  const seen: { type: string | null; body: string }[] = []
  listing()
  server.use(
    http.post('/api/resumes/upload', async ({ request }) => {
      // Read as text: jsdom builds the File and Node's undici serialises the
      // FormData, and undici does not recognise jsdom's File, so parsing it
      // back fails in this environment and nowhere else.
      seen.push({
        type: request.headers.get('content-type'),
        body: await request.text(),
      })

      return HttpResponse.json(resume(), { status: 201 })
    }),
  )

  show()
  await userEvent.upload(
    await screen.findByLabelText('Resume file (PDF, DOCX or text)'),
    new File(['ten years of python'], 'cv.txt', { type: 'text/plain' }),
  )
  const uploading = within(screen.getByRole('form', { name: 'Upload a resume' }))
  await userEvent.type(uploading.getByLabelText('Target role (optional)'), 'Backend')
  await userEvent.click(uploading.getByRole('button', { name: 'Upload' }))

  await waitFor(() => {
    expect(seen).toHaveLength(1)
  })
  expect(seen[0]?.type).toMatch(/^multipart\/form-data; boundary=/)
  expect(seen[0]?.body).toContain('name="file"')
  expect(seen[0]?.body).toContain('name="target_role"')
  expect(seen[0]?.body).toContain('Backend')
})

test('deleting asks first', async () => {
  // The one irreversible action on this page. A single press would delete a
  // resume on a mis-click, and there is no undo.
  const deleted: string[] = []
  listing(resume())
  server.use(
    http.delete('/api/resumes/:id', ({ params }) => {
      deleted.push(String(params.id))

      return new HttpResponse(null, { status: 204 })
    }),
  )

  show()
  await userEvent.click(await screen.findByRole('button', { name: 'Delete cv.pdf' }))

  expect(deleted).toEqual([])
  expect(screen.getByRole('button', { name: 'Really delete cv.pdf' })).toBeInTheDocument()
})

test('a confirmed delete removes the resume and says so', async () => {
  let present = true
  server.use(
    http.get('/api/resumes', () => HttpResponse.json(present ? [resume()] : [])),
    http.delete('/api/resumes/:id', () => {
      present = false

      return new HttpResponse(null, { status: 204 })
    }),
  )

  show()
  await userEvent.click(await screen.findByRole('button', { name: 'Delete cv.pdf' }))
  await userEvent.click(screen.getByRole('button', { name: 'Really delete cv.pdf' }))

  expect(await screen.findByText('No resumes yet.')).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Deleted cv.pdf.')
})

test('reading an uploaded resume says so while it takes', async () => {
  listing()
  server.use(
    http.post('/api/resumes/upload', async () => {
      await delay(50)

      return HttpResponse.json(resume(), { status: 201 })
    }),
  )

  show()
  await userEvent.upload(
    await screen.findByLabelText('Resume file (PDF, DOCX or text)'),
    new File(['ten years of python'], 'cv.txt', { type: 'text/plain' }),
  )
  await userEvent.click(screen.getByRole('button', { name: 'Upload' }))

  expect(await screen.findByText('Reading the resume…')).toBeInTheDocument()
})

test('a cancelled delete leaves the resume alone', async () => {
  const deleted: string[] = []
  listing(resume())
  server.use(
    http.delete('/api/resumes/:id', ({ params }) => {
      deleted.push(String(params.id))

      return new HttpResponse(null, { status: 204 })
    }),
  )

  show()
  await userEvent.click(await screen.findByRole('button', { name: 'Delete cv.pdf' }))
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))

  expect(deleted).toEqual([])
  expect(screen.getByRole('button', { name: 'Delete cv.pdf' })).toBeInTheDocument()
})

/** An export route that records what was asked for and answers with `body`. */
function exporting(asked: string[], status = 200): void {
  server.use(
    http.get('/api/resumes/:id/export', ({ params, request }) => {
      const format = new URL(request.url).searchParams.get('format') ?? ''
      asked.push(`${String(params.id)}.${format}`)

      if (status !== 200) {
        return HttpResponse.json({ detail: 'Not found' }, { status })
      }

      return new HttpResponse(`${format} bytes`, {
        headers: { 'Content-Type': 'application/octet-stream' },
      })
    }),
  )
}

test('every resume offers each format under its own name', async () => {
  listing(resume(), resume({ id: '01a0-other', original_filename: 'old.docx' }))

  show()

  for (const name of ['cv.pdf', 'old.docx']) {
    const group = await screen.findByRole('group', { name: `Download ${name}` })

    for (const label of ['PDF', 'Word', 'Markdown']) {
      expect(
        within(group).getByRole('button', { name: `Download ${name} as ${label}` }),
      ).toBeInTheDocument()
    }
  }
})

test.each([
  ['PDF', 'pdf'],
  ['Word', 'docx'],
  ['Markdown', 'md'],
])('a %s download fetches that format and saves it', async (label, format) => {
  const asked: string[] = []
  listing(resume())
  exporting(asked)

  show()
  await userEvent.click(
    await screen.findByRole('button', { name: `Download cv.pdf as ${label}` }),
  )

  await waitFor(() => {
    expect(saveFile).toHaveBeenCalledTimes(1)
  })
  const [blob, filename] = vi.mocked(saveFile).mock.calls[0] ?? []
  expect(asked).toEqual([`01a0-resume.${format}`])
  expect(filename).toBe(`resume-01a0-resume.${format}`)
  expect(await blob?.text()).toBe(`${format} bytes`)
})

test('the buttons are held while a download is on its way', async () => {
  // A second press would fetch and save the same file twice.
  let answer: () => void = () => undefined
  const held = new Promise<void>((resolve) => {
    answer = resolve
  })
  listing(resume())
  server.use(
    http.get('/api/resumes/:id/export', async () => {
      await held

      return new HttpResponse('pdf bytes')
    }),
  )

  show()
  await userEvent.click(
    await screen.findByRole('button', { name: 'Download cv.pdf as PDF' }),
  )

  for (const label of ['PDF', 'Word', 'Markdown']) {
    expect(
      screen.getByRole('button', { name: `Download cv.pdf as ${label}` }),
    ).toBeDisabled()
  }

  answer()
  await waitFor(() => {
    expect(saveFile).toHaveBeenCalledTimes(1)
  })
  expect(screen.getByRole('button', { name: 'Download cv.pdf as PDF' })).toBeEnabled()
})

test('a failed download says why and saves nothing', async () => {
  // The resume was deleted in another tab after this list was drawn.
  const asked: string[] = []
  listing(resume())
  exporting(asked, 404)

  show()
  await userEvent.click(
    await screen.findByRole('button', { name: 'Download cv.pdf as PDF' }),
  )

  expect(await screen.findByRole('alert')).toHaveTextContent('Not found')
  expect(saveFile).not.toHaveBeenCalled()
})

test('a stale session is renewed and the download still arrives', async () => {
  // The reason this is not a plain link: only the API client renews an
  // expired access cookie, and a link followed after it expired opens a 401.
  const calls: string[] = []
  let renewed = false
  listing(resume())
  server.use(
    http.get('/api/resumes/:id/export', () => {
      calls.push('export')

      return renewed
        ? new HttpResponse('pdf bytes')
        : new HttpResponse(null, { status: 401 })
    }),
    http.post('/api/auth/refresh', () => {
      calls.push('refresh')
      renewed = true

      return new HttpResponse(null, { status: 204 })
    }),
  )

  show()
  await userEvent.click(
    await screen.findByRole('button', { name: 'Download cv.pdf as PDF' }),
  )

  await waitFor(() => {
    expect(saveFile).toHaveBeenCalledTimes(1)
  })
  expect(calls).toEqual(['export', 'refresh', 'export'])
})
