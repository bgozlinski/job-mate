import type { ReactElement, ReactNode } from 'react'

/**
 * A sheet of paper on the page: told from it by a line, not lifted by a
 * shadow.
 *
 * With a `tab`, it is a file: the label sits on a tab over its top left
 * corner, as on a folder, and that corner goes square to meet it. The label
 * is plain text -- the sheet's heading stays inside, so the outline of the
 * page does not change.
 */
export function Sheet({
  children,
  tab,
  className = '',
}: {
  children: ReactNode
  tab?: ReactNode
  className?: string
}): ReactElement {
  const sheet = (
    <div
      className={
        'rounded-card border border-line bg-raised p-5 ' +
        (tab ? 'rounded-tl-none ' : '') +
        className
      }
    >
      {children}
    </div>
  )

  if (!tab) {
    return sheet
  }

  return (
    <div>
      {/* One pixel down, over the sheet's top line, so the two read as one. */}
      <div className="relative top-px inline-block rounded-t-card border border-b-0 border-line bg-raised px-3 py-1 text-sm font-semibold text-accent">
        {tab}
      </div>
      {sheet}
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
