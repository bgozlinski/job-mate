import type { ReactElement, ReactNode } from 'react'
import {
  CircleCheckIcon,
  InboxIcon,
  LoaderCircleIcon,
  TriangleAlertIcon,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

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

/**
 * A list with nothing in it yet, said as a sentence with the way out beside
 * it -- "No postings yet. Add one" -- rather than a blank area that looks the
 * same as one still loading.
 */
export function EmptyState({
  icon: Icon = InboxIcon,
  title,
  children,
  action,
}: {
  icon?: LucideIcon
  title: string
  children?: ReactNode
  action?: ReactNode
}): ReactElement {
  return (
    <div className="flex flex-col items-center gap-3 rounded-card border-[1.5px] border-dashed border-line px-6 py-10 text-center">
      <span className="rounded-full bg-sunken p-3 text-ink-faint">
        <Icon aria-hidden="true" className="size-6" />
      </span>
      <p className="font-bold">{title}</p>
      {children ? <p className="max-w-prose text-sm text-ink-soft">{children}</p> : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  )
}

/**
 * Grey blocks in the shape of what is about to arrive, instead of the word
 * "Loading…".
 *
 * The blocks mean nothing to a screen reader, so they are hidden from it and
 * the container says what is happening in words instead. The pulse only runs
 * when the system does not ask for reduced motion.
 */
export function Skeleton({
  lines = 3,
  label = 'Loading…',
}: {
  lines?: number
  label?: string
}): ReactElement {
  return (
    <div role="status" className="flex flex-col gap-3">
      <span className="sr-only">{label}</span>
      {Array.from({ length: lines }, (_, index) => (
        <div
          key={index}
          aria-hidden="true"
          data-testid="skeleton-block"
          className="h-16 rounded-card bg-sunken motion-safe:animate-pulse"
        />
      ))}
    </div>
  )
}

function Spin(): ReactElement {
  return (
    <LoaderCircleIcon
      aria-hidden="true"
      className="size-4 shrink-0 motion-safe:animate-spin"
    />
  )
}

/** Something short is under way; the sentence says what. */
export function Spinner({ children }: { children: ReactNode }): ReactElement {
  return (
    <p role="status" className="inline-flex items-center gap-2 text-sm text-ink-soft">
      <Spin />
      <span>{children}</span>
    </p>
  )
}

/**
 * Waiting on the language model -- a wait of several seconds, not a blink.
 *
 * More visible than Spinner on purpose: without it a person who pressed "Send"
 * sees nothing move for long enough to press it again.
 */
export function Thinking({ children }: { children: ReactNode }): ReactElement {
  return (
    <p
      role="status"
      className="inline-flex items-center gap-2 rounded-full bg-accent-soft px-4 py-2 text-sm font-semibold text-accent-strong"
    >
      <Spin />
      <span>{children}</span>
    </p>
  )
}
