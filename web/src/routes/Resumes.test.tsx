import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'

import { Providers, createQueryClient } from '../providers'
import { server } from '../test/server'
import { Resumes } from './Resumes'

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

test('an empty list says so rather than showing nothing', async () => {
  listing()

  show()

  expect(await screen.findByText('No resumes stored yet.')).toBeInTheDocument()
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

test('a confirmed delete removes the resume from the list', async () => {
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

  expect(await screen.findByText('No resumes stored yet.')).toBeInTheDocument()
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
