import type { ReactElement } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router'

import { useSession } from './session'

/**
 * Let a route render only once the API has said who is asking.
 *
 * Three states, not two. While the session query is in flight nothing is
 * rendered: sending the visitor to the login screen and pulling them back a
 * moment later is how a returning user, whose cookie is perfectly valid, sees
 * a login form flash on every reload.
 *
 * This is a convenience, not a boundary. Every route it guards is also
 * refused by the API to a caller with no session, which is where the actual
 * enforcement lives (NFR-1). Hiding a page in the browser protects nothing
 * on its own -- anybody can edit what runs in their own browser.
 */
export function RequireAuth(): ReactElement | null {
  const session = useSession()
  const location = useLocation()

  if (session.isPending) {
    return null
  }

  if (!session.data) {
    // Where they were going, so logging in can put them there instead of at
    // the front page -- which matters most for the links people share.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
