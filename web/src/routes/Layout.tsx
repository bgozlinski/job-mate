import type { ReactElement } from 'react'
import {
  BriefcaseIcon,
  FileTextIcon,
  GitCompareArrowsIcon,
  HistoryIcon,
  HouseIcon,
  LogOutIcon,
  MessagesSquareIcon,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Link, Outlet, useLocation } from 'react-router'

import { useLogout, useSession } from '../auth/session'
import { Button, ThemeToggle } from '../ui'

/**
 * `also` lists the pages that belong to a place without living under its
 * address: a match or an interview is part of your history.
 */
const TABS: { to: string; label: string; icon: LucideIcon; also: string[] }[] = [
  { to: '/', label: 'Home', icon: HouseIcon, also: [] },
  { to: '/documents', label: 'Postings', icon: BriefcaseIcon, also: [] },
  { to: '/resumes', label: 'Resumes', icon: FileTextIcon, also: [] },
  { to: '/match', label: 'Match', icon: GitCompareArrowsIcon, also: [] },
  { to: '/interview', label: 'Interview', icon: MessagesSquareIcon, also: [] },
  {
    to: '/history',
    label: 'History',
    icon: HistoryIcon,
    also: ['/matches/', '/interviews/'],
  },
]

/**
 * The frame every signed-in page is drawn in: who you are, where you can go,
 * and the way out. Rendered inside RequireAuth, so it only ever draws for a
 * caller the API has already confirmed.
 */
export function Layout(): ReactElement {
  const session = useSession()
  const logout = useLogout()
  const { pathname } = useLocation()

  return (
    <div className="min-h-dvh">
      <header className="border-b border-line bg-raised">
        {/* 6xl rather than 5xl so the places, the theme toggle and the account
            fit on one line at laptop width; main matches it so the logo stays
            aligned with the content under it. */}
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-6 py-3">
          <h1 className="text-xl font-extrabold tracking-tight">
            <Link to="/" className="rounded-md transition-colors hover:text-accent">
              Job<span className="text-accent">Mate</span>
            </Link>
          </h1>

          <nav aria-label="Main" className="flex flex-wrap gap-1">
            {TABS.map(({ to, label, icon: Icon, also }) => {
              // Home only at its own address: every other page is "under" /,
              // so a prefix test would mark it current everywhere.
              const active =
                to === '/'
                  ? pathname === '/'
                  : pathname === to ||
                    pathname.startsWith(`${to}/`) ||
                    also.some((prefix) => pathname.startsWith(prefix))

              return (
                <Link
                  key={to}
                  to={to}
                  // Worked out here rather than by NavLink, which only knows
                  // its own address: a match is part of History without
                  // living under /history. The current tab is marked by
                  // weight and a filled background, not by colour alone, and
                  // aria-current is what a screen reader announces.
                  aria-current={active ? 'page' : undefined}
                  className={
                    'inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm transition-colors ' +
                    (active
                      ? 'bg-accent-soft font-bold text-accent-strong'
                      : 'text-ink-soft hover:bg-sunken hover:text-accent')
                  }
                >
                  <Icon aria-hidden="true" className="size-4" />
                  {label}
                </Link>
              )
            })}
          </nav>

          <div className="ml-auto flex items-center gap-3 text-sm text-ink-faint">
            <ThemeToggle />
            {/* The address is on the way out rather than beside it: six places,
                the toggle and an address do not fit one line in 6xl, and who is
                signed in matters mostly when leaving. The title shows on hover
                and a screen reader reads it as the button's description. */}
            <Button
              type="button"
              variant="quiet"
              icon={LogOutIcon}
              title={session.data ? `Signed in as ${session.data.email}` : undefined}
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

      <main className="mx-auto flex max-w-6xl flex-col gap-10 px-6 py-8">
        <Outlet />
      </main>
    </div>
  )
}
