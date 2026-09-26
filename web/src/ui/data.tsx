import type { ReactElement, ReactNode } from 'react'
import { CheckIcon, XIcon } from 'lucide-react'

/** A ratio as a whole percentage: 0.72 is "72%". */
export function percentage(score: number): string {
  return `${String(Math.round(score * 100))}%`
}

/**
 * A score, set large on the page it belongs to and small in a row.
 *
 * Tabular figures, so scores in a column line up digit under digit.
 */
export function Score({
  value,
  size,
}: {
  value: number
  size: 'lg' | 'sm'
}): ReactElement {
  return (
    <span
      className={
        'font-extrabold text-accent tabular-nums ' +
        (size === 'lg' ? 'text-[2.5rem] leading-none tracking-tight' : '')
      }
    >
      {percentage(value)}
    </span>
  )
}

/**
 * A requirement, present or absent.
 *
 * Present is filled; absent is a stamp -- a red outline with a cross, the mark
 * a reviewer leaves on what is missing. Red against ink-blue alone would not
 * do: under deuteranopia that difference nearly vanishes, so the distinction
 * is carried by fill against outline, by the mark, by the heading above the
 * group and by the word itself. Four channels besides hue.
 */
export function Chip({
  present,
  children,
}: {
  present: boolean
  children: ReactNode
}): ReactElement {
  const Mark = present ? CheckIcon : XIcon

  return (
    <span
      className={
        'inline-flex items-center gap-1.5 rounded-control px-3 py-1 text-sm ' +
        (present
          ? 'bg-accent-soft font-semibold text-accent-strong'
          : 'border-[1.5px] border-danger font-semibold text-danger')
      }
    >
      <Mark aria-hidden="true" className="size-3.5 shrink-0" strokeWidth={3} />
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
      className="h-2.5 w-full overflow-hidden rounded-control bg-sunken"
    >
      <div
        className="h-full rounded-control bg-accent"
        style={{ width: `${String(percent)}%` }}
      />
    </div>
  )
}
