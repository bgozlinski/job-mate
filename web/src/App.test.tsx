import { render, screen, waitFor, within } from '@testing-library/react'
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

/** An account with nothing in it yet. Signing in lands on the dashboard, so
 *  every test that gets past the login screen needs it answered -- and the
 *  knowledge base, for the tests that go there. */
function newAccount(): void {
  server.use(
    http.get('/api/dashboard', () =>
      HttpResponse.json({ steps: [{ kind: 'add_resume' }, { kind: 'add_posting' }] }),
    ),
    http.get('/api/matches', () => HttpResponse.json([])),
    http.get('/api/sessions', () => HttpResponse.json([])),
    http.get('/api/documents', () => HttpResponse.json([])),
  )
}

function signedIn(): void {
  server.use(http.get('/api/auth/me', () => HttpResponse.json(USER)))
  newAccount()
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
  newAccount()

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
  newAccount()

  show('/')
  await userEvent.click(await screen.findByRole('button', { name: 'Log out' }))

  await waitFor(() => {
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
  })
})

test('signing in lands on what to do next', async () => {
  signedIn()

  show('/')

  expect(
    await screen.findByRole('heading', { level: 2, name: 'Add your resume' }),
  ).toBeInTheDocument()
})

test('the navigation offers six places, home first', async () => {
  signedIn()

  show('/documents')

  const nav = await screen.findByRole('navigation', { name: 'Main' })
  const places = within(nav)
    .getAllByRole('link')
    .map((link) => link.textContent)
  expect(places).toEqual([
    'Home',
    'Postings',
    'Resumes',
    'Match',
    'Interview',
    'History',
  ])
})

test.each([
  ['/', true],
  ['/documents', false],
])('on %s the Home place is current: %s', async (at, current) => {
  signedIn()

  show(at)

  const nav = within(await screen.findByRole('navigation', { name: 'Main' }))
  const home = nav.getByRole('link', { name: 'Home' })
  if (current) {
    expect(home).toHaveAttribute('aria-current', 'page')
  } else {
    expect(home).not.toHaveAttribute('aria-current')
  }
})

test('the logo leads home', async () => {
  signedIn()

  show('/documents')

  const banner = within(await screen.findByRole('banner'))
  expect(banner.getByRole('link', { name: 'JobMate' })).toHaveAttribute('href', '/')
})

test('a match belongs to History in the navigation', async () => {
  signedIn()
  server.use(
    http.get('/api/matches/m1', () =>
      HttpResponse.json({ detail: 'Not found' }, { status: 404 }),
    ),
  )

  show('/matches/m1')

  const nav = within(await screen.findByRole('navigation', { name: 'Main' }))
  expect(nav.getByRole('link', { name: 'History' })).toHaveAttribute(
    'aria-current',
    'page',
  )
  expect(nav.getByRole('link', { name: 'Postings' })).not.toHaveAttribute(
    'aria-current',
  )
})

test.each([
  ['/match', 'Match'],
  ['/interview', 'Interview'],
  ['/matches', 'History'],
  ['/interviews', 'History'],
])('the address %s is the %s place', async (from, place) => {
  signedIn()
  server.use(
    http.get('/api/matches', () => HttpResponse.json([])),
    http.get('/api/sessions', () => HttpResponse.json([])),
    http.get('/api/resumes', () => HttpResponse.json([])),
  )

  show(from)

  await waitFor(() => {
    const nav = within(screen.getByRole('navigation', { name: 'Main' }))
    expect(nav.getByRole('link', { name: place })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })
})
