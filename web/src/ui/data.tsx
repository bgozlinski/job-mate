import type { ReactElement, ReactNode } from 'react'
import { CheckIcon, XIcon } from 'lucide-react'

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
  const Mark = present ? CheckIcon : XIcon

  return (
    <span
      className={
        'inline-flex items-center gap-1.5 rounded-control px-3 py-1 text-sm ' +
        (present
          ? 'bg-accent-soft font-semibold text-accent-strong'
          : 'border-[1.5px] border-dashed border-control text-ink-soft')
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
