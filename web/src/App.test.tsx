import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'

import { App } from './App'
import { Providers, createQueryClient } from './providers'
import { server } from './test/server'

const USER = { id: '01', email: 'reader@example.com', created_at: '2026-09-07T00:00:00Z' }

function show(at = '/') {
  return render(
    <Providers client={createQueryClient()}>
      <MemoryRouter initialEntries={[at]}>
        <App />
      </MemoryRouter>
    </Providers>,
  )
}

/** Answer /auth/me as nobody, and /auth/refresh as no session to renew. */
function signedOut(): void {
  server.use(
    http.get('/api/auth/me', () => new HttpResponse(null, { status: 401 })),
    http.post('/api/auth/refresh', () => new HttpResponse(null, { status: 401 })),
  )
}

/** The knowledge base, empty. Signing in lands on it, so every test that
 *  gets past the login screen needs it answered. */
function emptyKnowledgeBase(): void {
  server.use(http.get('/api/documents', () => HttpResponse.json([])))
}

function signedIn(): void {
  server.use(http.get('/api/auth/me', () => HttpResponse.json(USER)))
  emptyKnowledgeBase()
}

test('a visitor with no session is sent to the login screen', async () => {
  signedOut()

  show('/')

  expect(await screen.findByLabelText('Email')).toBeInTheDocument()
})

test('a returning visitor is not shown the login screen', async () => {
  // The cookie is valid and unreadable from here, so the application has to
  // ask before deciding. Rendering the login form while that answer is in
  // flight is what makes a perfectly good session flash a login screen on
  // every reload.
  signedIn()

  show('/')

  expect(await screen.findByText(`Signed in as ${USER.email}`)).toBeInTheDocument()
  expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
})

test('logging in replaces the form with the application', async () => {
  let session = false

  server.use(
    http.get('/api/auth/me', () =>
      session ? HttpResponse.json(USER) : new HttpResponse(null, { status: 401 }),
    ),
    http.post('/api/auth/refresh', () => new HttpResponse(null, { status: 401 })),
    http.post('/api/auth/login', () => {
      session = true

      return HttpResponse.json({ access_token: 'x', token_type: 'bearer' })
    }),
  )
  emptyKnowledgeBase()

  show('/')
  await userEvent.type(await screen.findByLabelText('Email'), USER.email)
  await userEvent.type(screen.getByLabelText('Password'), 'secret123')
  await userEvent.click(screen.getByRole('button', { name: 'Log in' }))

  expect(await screen.findByText(`Signed in as ${USER.email}`)).toBeInTheDocument()
})

test('a rejected login says why, in the API’s own words', async () => {
  // The API answers the same 401 for a wrong password and for an address with
  // no account, so that this form cannot be used to discover who is
  // registered. Passing its message through keeps that true.
  signedOut()
  server.use(
    http.post('/api/auth/login', () =>
      HttpResponse.json({ detail: 'Invalid email or password' }, { status: 401 }),
    ),
  )

  show('/')
  await userEvent.type(await screen.findByLabelText('Email'), USER.email)
  await userEvent.type(screen.getByLabelText('Password'), 'wrong')
  await userEvent.click(screen.getByRole('button', { name: 'Log in' }))

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Invalid email or password',
  )
})

test('logging out returns to the login screen', async () => {
  let session = true

  server.use(
    http.get('/api/auth/me', () =>
      session ? HttpResponse.json(USER) : new HttpResponse(null, { status: 401 }),
    ),
    http.post('/api/auth/refresh', () => new HttpResponse(null, { status: 401 })),
    http.post('/api/auth/logout', () => {
      session = false

      return new HttpResponse(null, { status: 204 })
    }),
  )
  emptyKnowledgeBase()

  show('/')
  await userEvent.click(await screen.findByRole('button', { name: 'Log out' }))

  await waitFor(() => {
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
  })
})
