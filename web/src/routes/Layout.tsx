import type { ReactElement } from 'react'
import { NavLink, Outlet } from 'react-router'

import { useLogout, useSession } from '../auth/session'
import { Button } from '../ui'

const TABS = [
  { to: '/documents', label: 'Job postings' },
  { to: '/resumes', label: 'Resumes' },
  { to: '/match', label: 'Match' },
  { to: '/matches', label: 'History' },
]

/**
 * The frame every signed-in page is drawn in: who you are, where you can go,
 * and the way out. Rendered inside RequireAuth, so it only ever draws for a
 * caller the API has already confirmed.
 */
export function Layout(): ReactElement {
  const session = useSession()
  const logout = useLogout()

  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-raised">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-6 gap-y-3 px-6 py-3">
          <h1 className="text-lg font-bold tracking-tight">
            Job<span className="text-accent">Mate</span>
          </h1>

          <nav aria-label="Main" className="flex gap-1">
            {TABS.map((tab) => (
              <NavLink
                key={tab.to}
                to={tab.to}
                // The current tab is marked by weight and a filled background,
                // not by colour alone. NavLink sets aria-current regardless,
                // which is what a screen reader announces.
                className={({ isActive }) =>
                  'rounded-lg px-3 py-1.5 text-sm transition-colors ' +
                  (isActive
                    ? 'bg-accent-soft font-semibold text-accent-strong'
                    : 'text-ink-soft hover:text-accent')
                }
              >
                {tab.label}
              </NavLink>
            ))}
          </nav>

          <p className="ml-auto flex items-center gap-2 text-sm text-ink-faint">
            <span className="hidden sm:inline">
              Signed in as {session.data?.email}
            </span>
            <Button
              type="button"
              variant="quiet"
              disabled={logout.isPending}
              onClick={() => {
                logout.mutate()
              }}
            >
              Log out
            </Button>
          </p>
        </div>
      </header>

      <main className="mx-auto flex max-w-5xl flex-col gap-10 px-6 py-8">
        <Outlet />
      </main>
    </div>
  )
}
