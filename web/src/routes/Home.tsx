import type { ReactElement } from 'react'

import { useLogout, useSession } from '../auth/session'

/**
 * The signed-in shell. Its panels arrive in B4 to B6; what it proves today is
 * that the cookie session survives a reload and can be ended.
 */
export function Home(): ReactElement {
  const session = useSession()
  const logout = useLogout()

  return (
    <main>
      <h1>JobMate</h1>
      <p>Signed in as {session.data?.email}</p>

      <button
        type="button"
        disabled={logout.isPending}
        onClick={() => {
          logout.mutate()
        }}
      >
        Log out
      </button>
    </main>
  )
}
