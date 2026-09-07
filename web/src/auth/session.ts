import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from '../api/client'
import { detailOf } from '../api/errors'
import type { components } from '../api/schema'

export type User = components['schemas']['UserRead']
export type Credentials = components['schemas']['LoginRequest']

export const sessionKey = ['session'] as const

/**
 * Ask the API who the caller is, or say that it is nobody.
 *
 * There is nothing on this page to read the session from: it lives in an
 * httpOnly cookie, so the only way to learn whether somebody is logged in is
 * to ask. This runs once when the application starts, and its answer is what
 * decides between the login screen and the application.
 *
 * A 401 is an answer, not a failure. It means no session, which is a normal
 * state for a first visit and must not be reported as an error or retried.
 * Everything else -- the API being down, a 500 -- throws, because "we could
 * not tell" is genuinely different from "nobody is logged in" and only one
 * of them should send a returning user to a login form.
 */
async function fetchSession(): Promise<User | null> {
  const { data, response } = await api.GET('/auth/me')

  if (response.status === 401) {
    return null
  }

  if (!data) {
    throw new Error(`Could not read the session (${String(response.status)})`)
  }

  return data
}

export function useSession(): UseQueryResult<User | null> {
  return useQuery({
    queryKey: sessionKey,
    queryFn: fetchSession,
    // A session does not change behind the application's back, and every
    // mutation below updates this cache itself. Refetching on every window
    // focus would put a request on the API each time the user comes back to
    // the tab, to be told what it already knows.
    staleTime: Infinity,
    // fetchSession already distinguishes "no session" from "could not ask";
    // retrying would only repeat a real outage three times before showing it.
    retry: false,
  })
}

async function submit(
  path: '/auth/login' | '/auth/register',
  credentials: Credentials,
): Promise<void> {
  const { error, response } = await api.POST(path, { body: credentials })

  if (error ?? !response.ok) {
    // The API answers 401 for a wrong password and for an address that has no
    // account, deliberately and identically, so that nobody can use this form
    // to find out which addresses are registered. Passing its message through
    // rather than inventing one keeps that property.
    throw new Error(
      detailOf(error) ?? `Request failed (${String(response.status)})`,
    )
  }
}

/**
 * Log in, then let the session query fetch who that turned out to be.
 *
 * Invalidating rather than writing the user into the cache: the login
 * response carries a token for the other kind of client, not the account,
 * and inventing a User from the address that was typed would put something
 * in the cache the server never said.
 */
export function useLogin(): UseMutationResult<void, Error, Credentials> {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (credentials: Credentials) => submit('/auth/login', credentials),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: sessionKey })
    },
  })
}

/** Register, and log the new account in with the same credentials. */
export function useRegister(): UseMutationResult<void, Error, Credentials> {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async (credentials: Credentials) => {
      await submit('/auth/register', credentials)
      await submit('/auth/login', credentials)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: sessionKey })
    },
  })
}

/**
 * End the session, and forget everything fetched for it.
 *
 * clear() rather than invalidating the session alone: every other cached
 * query -- resumes, matches -- belongs to the account that is leaving, and
 * leaving them in place would show one user's data to the next person to log
 * in on this machine before the refetch replaced it.
 */
export function useLogout(): UseMutationResult<void, Error, void> {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: async () => {
      await api.POST('/auth/logout')
    },
    onSettled: () => {
      // onSettled, not onSuccess: if the request failed the cookies may be
      // gone anyway, and a user who pressed Log out must not be left looking
      // at a page that still shows their data.
      // Write the logged-out state, then drop everything else. Order and
      // method both matter. clear() would empty the mutation cache as well --
      // including this very mutation, mid-callback -- and it leaves the
      // mounted components with no cached answer and no request in flight,
      // which renders as a signed-in shell with nothing in it. Saying
      // outright that there is no session is instant and needs no round trip
      // to be told what we already know.
      queryClient.setQueryData(sessionKey, null)
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] !== sessionKey[0],
      })
    },
  })
}
