import type { ReactElement, ReactNode } from 'react'
import { CircleCheckIcon, TriangleAlertIcon } from 'lucide-react'

/**
 * A failure the reader has to act on. role="alert" so it is announced.
 *
 * Red, but never only red: the icon and the sentence say it is an error too,
 * so it reads as one to someone who cannot tell the colour apart.
 */
export function Alert({ children }: { children: ReactNode }): ReactElement {
  return (
    <p
      role="alert"
      className="flex items-start gap-2 rounded-xl bg-danger-soft px-3 py-2.5 text-sm text-danger-ink"
    >
      <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>{children}</span>
    </p>
  )
}

/** An outcome worth reporting that is not a failure. */
export function Status({ children }: { children: ReactNode }): ReactElement {
  return (
    <p
      role="status"
      className="flex items-start gap-2 rounded-xl bg-accent-soft px-3 py-2.5 text-sm text-accent-strong"
    >
      <CircleCheckIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span>{children}</span>
    </p>
  )
}
