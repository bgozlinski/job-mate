import type { ReactElement, ReactNode } from 'react'

/**
 * A raised panel. Lifted by a soft shadow in the light theme; in the dark one
 * the shadow token is an outline instead, because a shadow barely shows on a
 * dark surface.
 */
export function Card({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}): ReactElement {
  return (
    <div className={`rounded-card bg-raised p-5 shadow-card ${className}`}>
      {children}
    </div>
  )
}

export function PageTitle({ children }: { children: ReactNode }): ReactElement {
  return <h2 className="text-2xl font-extrabold tracking-tight">{children}</h2>
}

/**
 * The top of a page: its title, a sentence on what the page is for, and the
 * page's own actions on the right (wrapping under the title when narrow).
 *
 * One component rather than each screen composing a title and a link by hand,
 * so every page starts the same way and the eye knows where to look.
 */
export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string
  description?: ReactNode
  actions?: ReactNode
}): ReactElement {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
      <div className="flex max-w-prose flex-col gap-1">
        <PageTitle>{title}</PageTitle>
        {description ? <Muted>{description}</Muted> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  )
}

export function Muted({ children }: { children: ReactNode }): ReactElement {
  return <p className="text-sm text-ink-faint">{children}</p>
}
