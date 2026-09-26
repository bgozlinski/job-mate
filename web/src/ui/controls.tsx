import type { ComponentPropsWithoutRef, ReactElement, ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Link } from 'react-router'
import type { LinkProps } from 'react-router'

const BUTTON_BASE =
  'inline-flex items-center justify-center gap-2 rounded-full font-semibold ' +
  'transition-colors disabled:cursor-not-allowed disabled:opacity-50'

const VARIANTS = {
  primary: 'bg-accent text-on-accent hover:bg-accent-strong',
  secondary: 'border border-control bg-raised text-ink hover:border-accent hover:text-accent',
  quiet: 'text-ink-soft hover:bg-sunken hover:text-accent',
  // For the one press that cannot be undone. The label still says what it
  // does; the colour only repeats it.
  danger: 'bg-danger text-on-danger hover:opacity-90',
} as const

const SIZES = {
  md: 'px-4 py-2 text-sm',
  sm: 'px-3 py-1 text-xs',
} as const

interface Look {
  variant?: keyof typeof VARIANTS
  size?: keyof typeof SIZES
  icon?: LucideIcon
}

function classesFor(
  variant: keyof typeof VARIANTS,
  size: keyof typeof SIZES,
  className: string,
): string {
  return `${BUTTON_BASE} ${VARIANTS[variant]} ${SIZES[size]} ${className}`
}

/**
 * A button, and nothing but one: whatever is passed goes onto the <button>,
 * so a label, aria-label and type work as they do on the element.
 *
 * The icon is decoration beside the label, hidden from screen readers -- the
 * label already says what the button does.
 */
export function Button({
  variant = 'primary',
  size = 'md',
  icon: Icon,
  className = '',
  children,
  ...props
}: ComponentPropsWithoutRef<'button'> & Look): ReactElement {
  return (
    <button {...props} className={classesFor(variant, size, className)}>
      {Icon ? <Icon aria-hidden="true" className="size-4 shrink-0" /> : null}
      {children}
    </button>
  )
}

/**
 * A link that looks like a button, for an action that only goes somewhere.
 *
 * Still an <a>: it opens in a new tab, and a screen reader announces a link.
 * It has no disabled state, because a link has none -- when there is nowhere
 * to go, the page leaves it out.
 */
export function ButtonLink({
  variant = 'primary',
  size = 'md',
  icon: Icon,
  className = '',
  children,
  ...props
}: LinkProps & Look): ReactElement {
  return (
    <Link {...props} className={classesFor(variant, size, className)}>
      {Icon ? <Icon aria-hidden="true" className="size-4 shrink-0" /> : null}
      {children}
    </Link>
  )
}

/**
 * What every text field, select and textarea looks like.
 *
 * The border is --control, not --line: a field has to show where it is, which
 * takes 3:1 against its surroundings, and --line is too faint for that.
 */
export const CONTROL =
  'w-full rounded-xl border border-control bg-raised px-3 py-2 text-sm ' +
  'text-ink placeholder:text-ink-faint transition-colors ' +
  'hover:border-ink-soft focus-visible:border-accent'

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
      <label htmlFor={id} className="text-sm font-semibold text-ink-soft">
        {label}
      </label>
      {children(CONTROL, id)}
      {hint ? <p className="text-xs text-ink-faint">{hint}</p> : null}
    </div>
  )
}
