import type { ReactElement } from 'react'
import {
  BriefcaseIcon,
  FileTextIcon,
  GitCompareArrowsIcon,
  HistoryIcon,
  LogOutIcon,
  MessagesSquareIcon,
} from 'lucide-react'
import { NavLink, Outlet } from 'react-router'

import { useLogout, useSession } from '../auth/session'
import { Button, ThemeToggle } from '../ui'

const TABS = [
  { to: '/documents', label: 'Job postings', icon: BriefcaseIcon },
  { to: '/resumes', label: 'Resumes', icon: FileTextIcon },
  { to: '/match', label: 'Match', icon: GitCompareArrowsIcon },
  { to: '/matches', label: 'History', icon: HistoryIcon },
  { to: '/interview', label: 'Interview', icon: MessagesSquareIcon },
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
          <h1 className="text-xl font-extrabold tracking-tight">
            Job<span className="text-accent">Mate</span>
          </h1>

          <nav aria-label="Main" className="flex flex-wrap gap-1">
            {TABS.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                // The current tab is marked by weight and a filled background,
                // not by colour alone. NavLink sets aria-current regardless,
                // which is what a screen reader announces.
                className={({ isActive }) =>
                  'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm transition-colors ' +
                  (isActive
                    ? 'bg-accent-soft font-bold text-accent-strong'
                    : 'text-ink-soft hover:bg-sunken hover:text-accent')
                }
              >
                <Icon aria-hidden="true" className="size-4" />
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3 text-sm text-ink-faint">
            <ThemeToggle />
            <span className="hidden sm:inline">
              Signed in as {session.data?.email}
            </span>
            <Button
              type="button"
              variant="quiet"
              icon={LogOutIcon}
              disabled={logout.isPending}
              onClick={() => {
                logout.mutate()
              }}
            >
              Log out
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto flex max-w-5xl flex-col gap-10 px-6 py-8">
        <Outlet />
      </main>
    </div>
  )
}
