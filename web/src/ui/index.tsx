import type { ComponentPropsWithoutRef, ReactElement, ReactNode } from 'react'

/**
 * The handful of shapes every screen is built from.
 *
 * They exist because of what Tailwind costs at this size: nine components, each
 * repeating the same dozen utility classes for a button or a labelled field, is
 * a diff nobody can review and a change nobody can make in one place. Layout
 * stays in utility classes at the call site, where it differs; anything
 * repeated lives here.
 *
 * Each one renders exactly the markup it replaced -- a button is a <button>, a
 * field is a <label> and an <input> sharing an id. The forty tests query by
 * role and label and were not touched, so if one of them fails, this refactor
 * changed behaviour rather than appearance.
 */

const BUTTON_BASE =
  'inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 ' +
  'text-sm font-medium transition-colors disabled:cursor-not-allowed ' +
  'disabled:opacity-50'

const VARIANTS = {
  primary: 'bg-accent text-on-accent hover:bg-accent-strong',
  secondary: 'border border-line bg-raised text-ink hover:border-accent',
  quiet: 'text-ink-soft hover:text-accent',
} as const

export function Button({
  variant = 'primary',
  className = '',
  ...props
}: ComponentPropsWithoutRef<'button'> & {
  variant?: keyof typeof VARIANTS
}): ReactElement {
  return (
    <button
      {...props}
      className={`${BUTTON_BASE} ${VARIANTS[variant]} ${className}`}
    />
  )
}

const CONTROL =
  'w-full rounded-lg border border-line bg-raised px-3 py-2 text-sm ' +
  'text-ink placeholder:text-ink-faint'

/** A label bound to a control by id, which is what the tests find them by. */
export function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string
  label: string
  hint?: string
  children: (className: string, id: string) => ReactNode
}): ReactElement {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-ink-soft">
        {label}
      </label>
      {children(CONTROL, id)}
      {hint ? <p className="text-xs text-ink-faint">{hint}</p> : null}
    </div>
  )
}

export function Card({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}): ReactElement {
  return (
    <div
      className={`rounded-card border border-line bg-raised p-4 ${className}`}
    >
      {children}
    </div>
  )
}

/**
 * A requirement, present or absent.
 *
 * Filled against outlined, not green against red. Those two measure a colour
 * difference of 4.1 under deuteranopia -- the same colour to roughly one man in
 * sixteen -- so the distinction is carried by fill, by a mark, by the heading
 * above the group and by the word itself. Four channels, none of them hue.
 */
export function Chip({
  present,
  children,
}: {
  present: boolean
  children: ReactNode
}): ReactElement {
  return (
    <span
      className={
        'inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm ' +
        (present
          ? 'bg-accent-soft text-accent-strong'
          : 'border border-dashed border-line text-ink-soft')
      }
    >
      <span aria-hidden="true">{present ? '✓' : '✗'}</span>
      {children}
    </span>
  )
}

/**
 * A single ratio against a limit, drawn on a track of its own ramp.
 *
 * One hue, never one that shifts from red to green with the value: that is a
 * diverging encoding, and it reintroduces exactly the pair a colour-vision
 * check rejects. The number beside it already says whether 50% is good news.
 */
export function Meter({ value, label }: { value: number; label: string }): ReactElement {
  const percent = Math.round(value * 100)

  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      className="h-2 w-full overflow-hidden rounded-full bg-line"
    >
      <div
        className="h-full rounded-full bg-accent"
        style={{ width: `${String(percent)}%` }}
      />
    </div>
  )
}

/** A failure the reader has to act on. role="alert" so it is announced. */
export function Alert({ children }: { children: ReactNode }): ReactElement {
  return (
    <p
      role="alert"
      className="rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink"
    >
      {children}
    </p>
  )
}

/** An outcome worth reporting that is not a failure. */
export function Status({ children }: { children: ReactNode }): ReactElement {
  return (
    <p
      role="status"
      className="rounded-lg bg-accent-soft px-3 py-2 text-sm text-accent-strong"
    >
      {children}
    </p>
  )
}

export function PageTitle({ children }: { children: ReactNode }): ReactElement {
  return <h2 className="text-xl font-semibold tracking-tight">{children}</h2>
}

export function Muted({ children }: { children: ReactNode }): ReactElement {
  return <p className="text-sm text-ink-faint">{children}</p>
}
