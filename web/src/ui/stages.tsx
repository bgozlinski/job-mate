import type { ReactElement } from 'react'

import { percentage } from './data'

/** Where a posting stands for you: 1 added, 2 matched, 3 interviewed. */
export type Reached = 1 | 2 | 3

const STEPS = ['Posting', 'Match', 'Interview', 'Applied'] as const

/**
 * The step that cannot be reached yet: tracking sent applications is a later
 * project, so the rail keeps its place without offering it.
 */
const LATER = 4

/**
 * The steps of an application, drawn as a path.
 *
 * `reached` is the last step done, so the step after it is the next one to
 * take -- a posting matched but not practised has reached 2, and Interview is
 * marked as next. After an interview nothing is next, because Applied cannot
 * be recorded yet.
 *
 * A numbered list, because the steps are a sequence. Position alone does not
 * tell a screen reader what is done, so each step says it in words; the
 * compact form, for rows of a list, is four bars and one sentence.
 */
export function StageRail({
  reached,
  score,
  compact = false,
}: {
  reached: Reached
  score?: number | null
  compact?: boolean
}): ReactElement {
  const next = reached + 1 < LATER ? reached + 1 : null

  if (compact) {
    const name = STEPS[reached - 1] ?? ''

    return (
      <span className="inline-flex items-center gap-0.5">
        <span className="sr-only">{`Stage ${String(reached)} of ${String(STEPS.length)}: ${name}`}</span>
        {STEPS.map((step, index) => (
          <span
            key={step}
            aria-hidden="true"
            className={
              'h-1 w-3.5 rounded-control ' +
              (index < reached ? 'bg-accent' : 'bg-line')
            }
          />
        ))}
      </span>
    )
  }

  return (
    <ol aria-label="Stage" className="grid grid-cols-4 text-sm">
      {STEPS.map((step, index) => {
        const number = index + 1
        const done = number <= reached
        const isNext = number === next
        const later = number === LATER

        return (
          <li
            key={step}
            aria-current={isNext ? 'step' : undefined}
            className={
              'border-t-[3px] px-2 py-1.5 ' +
              (later ? 'border-dashed ' : '') +
              (isNext
                ? 'border-accent bg-accent-soft font-extrabold text-accent-strong'
                : done
                  ? 'border-accent font-semibold text-accent'
                  : 'border-line text-ink-faint')
            }
          >
            {`${String(number)} ${step}`}
            {step === 'Match' && score != null ? ` ${percentage(score)}` : null}
            <span className="sr-only">
              {later ? ', coming later' : done ? ', done' : ', not yet'}
            </span>
          </li>
        )
      })}
    </ol>
  )
}
