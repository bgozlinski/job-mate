import createClient from 'openapi-fetch'

import type { paths } from './schema'

export const API_PATH = '/api'

// Absolute, though it names this very origin. The page is served here and
// /api is proxied to the API (see vite.config.ts and nginx.conf), so a
// relative base would be correct in a browser -- but the Request constructor
// under test resolves nothing, and a relative URL there is a parse error
// rather than a same-origin request. Building it from location.origin keeps
// one code path for both.
export const API_BASE = new URL(API_PATH, globalThis.location.origin).toString()

const REFRESH_PATH = `${API_PATH}/auth/refresh`

// Paths that must never trigger a renewal. Logging in with the wrong password
// answers 401, and so does a refresh whose cookie has expired; treating
// either as "the access cookie went stale" would send a second request to
// answer a question already answered, and for /auth/refresh it would be a
// request to renew a renewal that just failed.
const NEVER_RETRIED = [REFRESH_PATH, `${API_PATH}/auth/login`]

let renewal: Promise<boolean> | null = null

/**
 * Ask for a new access cookie, at most one request at a time.
 *
 * Coalesced because a page renders several panels at once: let the access
 * cookie expire and five requests come back 401 within a few milliseconds.
 * Five independent renewals would then race to set the same cookie, and four
 * of them would be spending a refresh token to learn what the first already
 * knew.
 *
 * The promise is cleared once it settles, so the next expiry starts a fresh
 * one rather than replaying this answer.
 */
function renewSession(): Promise<boolean> {
  renewal ??= fetch(new URL(REFRESH_PATH, API_BASE), {
    method: 'POST',
    credentials: 'include',
  })
    .then((response) => response.ok)
    .catch(() => false)
    .finally(() => {
      renewal = null
    })

  return renewal
}

/**
 * Send a request, and if the session had merely gone stale, send it again.
 *
 * The access cookie lives fifteen minutes and nothing on this page can read
 * it, so the only way to discover it has expired is to be told 401. This is
 * the whole of what the httpOnly session costs the client: no token to store,
 * one place that notices the expiry and retries.
 *
 * Retried once and never in a loop. A second 401 after a successful renewal
 * means the request is genuinely unauthorised -- somebody else's resume, an
 * account since deleted -- and asking again would only produce it forever.
 *
 * The request is cloned before the first attempt because a body can only be
 * read once: retrying the original after it has been sent uploads nothing,
 * which turns a resume upload into a silent 422.
 */
async function fetchWithRenewal(input: Request): Promise<Response> {
  const retryable = input.clone()
  const response = await fetch(input)

  if (
    response.status !== 401 ||
    NEVER_RETRIED.includes(new URL(input.url).pathname)
  ) {
    return response
  }

  if (!(await renewSession())) {
    return response
  }

  return fetch(retryable)
}

export const api = createClient<paths>({
  baseUrl: API_BASE,
  // Same origin, so cookies would travel under the default anyway. Stated
  // outright because it is the only thing carrying the session: a reader
  // looking for where authentication happens should find it here and not
  // conclude there is none.
  credentials: 'include',
  fetch: fetchWithRenewal,
})
