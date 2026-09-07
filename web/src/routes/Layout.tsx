import type { ReactElement } from 'react'
import { NavLink, Outlet } from 'react-router'

import { useLogout, useSession } from '../auth/session'

/**
 * The frame every signed-in page is drawn in: who you are, where you can go,
 * and the way out. Rendered inside RequireAuth, so it only ever draws for a
 * caller the API has already confirmed.
 */
export function Layout(): ReactElement {
  const session = useSession()
  const logout = useLogout()

  return (
    <>
      <header>
        <h1>JobMate</h1>

        <nav aria-label="Main">
          <NavLink to="/documents">Job postings</NavLink>
          <NavLink to="/resumes">Resumes</NavLink>
        </nav>

        <p>
          Signed in as {session.data?.email}{' '}
          <button
            type="button"
            disabled={logout.isPending}
            onClick={() => {
              logout.mutate()
            }}
          >
            Log out
          </button>
        </p>
      </header>

      <main>
        <Outlet />
      </main>
    </>
  )
}
