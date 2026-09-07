import { HttpResponse, http } from 'msw'
import { beforeEach, describe, expect, test } from 'vitest'

import { server } from '../test/server'
import { api } from './client'

const ME = '/api/auth/me'
const REFRESH = '/api/auth/refresh'
const LOGIN = '/api/auth/login'

let calls: string[] = []

beforeEach(() => {
  calls = []
})

/** A handler that records the call and answers 401 until the session renews. */
function staleUntilRenewed(): void {
  let renewed = false

  server.use(
    http.get(ME, () => {
      calls.push('me')

      return renewed
        ? HttpResponse.json({ id: '1', email: 'a@b.c' })
        : new HttpResponse(null, { status: 401 })
    }),
    http.post(REFRESH, () => {
      calls.push('refresh')
      renewed = true

      return new HttpResponse(null, { status: 204 })
    }),
  )
}

describe('a stale access cookie', () => {
  test('is renewed and the request is sent again', async () => {
    staleUntilRenewed()

    const { data } = await api.GET('/auth/me')

    expect(data?.email).toBe('a@b.c')
    expect(calls).toEqual(['me', 'refresh', 'me'])
  })

  test('costs one renewal however many requests noticed it', async () => {
    // The reason renewSession is coalesced: a page renders several panels at
    // once, so an expiry surfaces as a handful of 401s within milliseconds.
    // Without this, each would spend the refresh token to learn the same
    // thing, and they would race to set the same cookie.
    staleUntilRenewed()

    await Promise.all([
      api.GET('/auth/me'),
      api.GET('/auth/me'),
      api.GET('/auth/me'),
    ])

    expect(calls.filter((call) => call === 'refresh')).toHaveLength(1)
  })
})

describe('a session that is really over', () => {
  test('is reported, not retried in a loop', async () => {
    server.use(
      http.get(ME, () => {
        calls.push('me')

        return new HttpResponse(null, { status: 401 })
      }),
      http.post(REFRESH, () => {
        calls.push('refresh')

        return new HttpResponse(null, { status: 401 })
      }),
    )

    const { response } = await api.GET('/auth/me')

    expect(response.status).toBe(401)
    expect(calls).toEqual(['me', 'refresh'])
  })

  test('does not turn one failed login into two', async () => {
    // 401 from /auth/login means the password was wrong, not that a cookie
    // went stale. Renewing here would ask the API to answer a question it has
    // already answered.
    server.use(
      http.post(LOGIN, () => {
        calls.push('login')

        return HttpResponse.json({ detail: 'Invalid email or password' }, {
          status: 401,
        })
      }),
    )

    const { response } = await api.POST('/auth/login', {
      body: { email: 'a@b.c', password: 'wrong' },
    })

    expect(response.status).toBe(401)
    expect(calls).toEqual(['login'])
  })
})

test('a retried request still carries its body', async () => {
  // A Request body can only be read once, so retrying the original after it
  // has been sent uploads nothing. The symptom would be a resume that
  // uploads fine while the session is fresh and silently arrives empty
  // fifteen minutes later.
  const bodies: unknown[] = []
  let renewed = false

  server.use(
    http.post('/api/documents', async ({ request }) => {
      bodies.push(await request.json())

      return renewed
        ? HttpResponse.json({ id: '1' }, { status: 201 })
        : new HttpResponse(null, { status: 401 })
    }),
    http.post(REFRESH, () => {
      renewed = true

      return new HttpResponse(null, { status: 204 })
    }),
  )

  await api.POST('/documents', { body: { content: 'a posting' } })

  expect(bodies).toHaveLength(2)
  expect(bodies[0]).toEqual({ content: 'a posting' })
  expect(bodies[1]).toEqual({ content: 'a posting' })
})
