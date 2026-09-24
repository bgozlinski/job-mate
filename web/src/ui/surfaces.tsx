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

export function Muted({ children }: { children: ReactNode }): ReactElement {
  return <p className="text-sm text-ink-faint">{children}</p>
}
