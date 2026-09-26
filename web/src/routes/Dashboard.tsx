import type { ReactElement } from 'react'
import {
  FileTextIcon,
  GitCompareArrowsIcon,
  MessagesSquareIcon,
  PlusIcon,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Link, useNavigate } from 'react-router'

import { useDashboard } from '../api/dashboard'
import type { Step } from '../api/dashboard'
import { useInterviews, useStartInterview } from '../api/interview'
import { useMatch, useMatches } from '../api/matching'
import type { Pairing } from '../api/matching'
import { ago } from '../time'
import {
  Alert,
  Button,
  ButtonLink,
  Chip,
  Score,
  Sheet,
  Skeleton,
  StageRail,
  Thinking,
  percentage,
} from '../ui'
import type { Reached } from '../ui'
import { newestFirst } from './timeline'

/** How much of your history the dashboard shows; the rest is on History. */
const RECENT = 5

/** Gaps shown on the next step; a long posting's list would bury the action. */
const GAPS_SHOWN = 5

type Action =
  | { kind: 'link'; to: string; label: string; name?: string; icon: LucideIcon }
  | { kind: 'match' | 'practise'; pairing: Pairing; label: string; name: string }

interface Described {
  sentence: string
  detail?: string
  action: Action
}

/**
 * Put one step into words and name the one thing to do about it.
 *
 * Exhaustive over `kind`: a step the API learns later fails the typecheck
 * here, rather than drawing nothing on the page.
 */
function describe(step: Step): Described {
  switch (step.kind) {
    case 'add_resume':
      return {
        sentence: 'Add your resume',
        detail: 'Matching and interviews start from it.',
        action: { kind: 'link', to: '/resumes', label: 'Add resume', icon: FileTextIcon },
      }
    case 'add_posting':
      return {
        sentence: 'Add a job posting',
        action: { kind: 'link', to: '/documents', label: 'Add posting', icon: PlusIcon },
      }
    case 'add_another_posting':
      return {
        sentence: "You're up to date",
        detail: 'Add another posting to keep going.',
        action: { kind: 'link', to: '/documents', label: 'Add posting', icon: PlusIcon },
      }
    case 'continue_interview': {
      const title = titleOf(step.document_title)

      return {
        sentence: `Finish your interview for ${title}`,
        detail: `${String(step.answered)} of ${String(step.question_count)} questions answered.`,
        action: {
          kind: 'link',
          to: `/interviews/${step.session_id}`,
          label: 'Continue',
          name: `Continue your interview for ${title}`,
          icon: MessagesSquareIcon,
        },
      }
    }
    case 'match': {
      const title = titleOf(step.document_title)

      return {
        sentence: `See how your resume fits ${title}`,
        action: {
          kind: 'match',
          pairing: { resumeId: step.resume_id, documentId: step.document_id },
          label: 'Match',
          name: `Match my resume with ${title}`,
        },
      }
    }
    case 'practise': {
      const title = titleOf(step.document_title)

      return {
        sentence: `Practise for ${title}`,
        detail: `Your resume matched ${percentage(step.score)}.`,
        action: {
          kind: 'practise',
          pairing: { resumeId: step.resume_id, documentId: step.document_id },
          label: 'Start interview',
          name: `Start interview for ${title}`,
        },
      }
    }
    default: {
      const unknown: never = step

      return unknown
    }
  }
}

/** The posting a step is about, and how far along it you are. */
interface Place {
  title: string
  reached: Reached
  score: number | null
  gaps: string[]
}

/**
 * Where a step stands on the path of an application, or null for a step that
 * is not about a posting.
 *
 * The rail marks the step after `reached` as next, so each kind maps to the
 * stage before the one it asks for. An interview in progress is still the
 * step to take, so it maps to 2 like practice does -- even when it was started
 * without a match, which the step cannot tell. The dashboard is about what to
 * do next, and for that the approximation is exact.
 */
function placeOf(step: Step): Place | null {
  switch (step.kind) {
    case 'match':
      return { title: titleOf(step.document_title), reached: 1, score: null, gaps: [] }
    case 'practise':
      return {
        title: titleOf(step.document_title),
        reached: 2,
        score: step.score,
        gaps: step.gaps,
      }
    case 'continue_interview':
      return { title: titleOf(step.document_title), reached: 2, score: null, gaps: [] }
    default:
      return null
  }
}

function titleOf(title: string | null): string {
  return title ?? 'an untitled posting'
}

function keyOf(step: Step): string {
  if (step.kind === 'continue_interview') {
    return `${step.kind}-${step.session_id}`
  }

  return 'document_id' in step ? `${step.kind}-${step.document_id}` : step.kind
}

/** What the two model-calling actions share: one wait at a time, page-wide. */
interface Running {
  busy: boolean
  pendingFor: (pairing: Pairing) => boolean
  errorFor: (pairing: Pairing) => Error | null
  run: (action: Extract<Action, { pairing: Pairing }>) => void
}

function useRunning(): Running {
  const match = useMatch()
  const start = useStartInterview()
  const navigate = useNavigate()

  // A posting appears in at most one step -- the API gives each posting one
  // kind -- so the posting alone says which step is waiting or failed.
  const matchFor = (pairing: Pairing): boolean =>
    match.variables?.documentId === pairing.documentId
  const startFor = (pairing: Pairing): boolean =>
    start.variables?.documentId === pairing.documentId

  return {
    busy: match.isPending || start.isPending,
    pendingFor: (pairing) =>
      (match.isPending && matchFor(pairing)) || (start.isPending && startFor(pairing)),
    errorFor: (pairing) =>
      (matchFor(pairing) ? match.error : null) ?? (startFor(pairing) ? start.error : null),
    run: (action) => {
      // Reset the other one, so a failure left from it is not shown beside a
      // step that has nothing to do with it any more.
      if (action.kind === 'match') {
        start.reset()
        match.mutate(action.pairing, {
          onSuccess: (result) => {
            void navigate(`/matches/${result.id}`)
          },
        })
      } else {
        match.reset()
        start.mutate(action.pairing, {
          onSuccess: (interview) => {
            void navigate(`/interviews/${interview.id}`)
          },
        })
      }
    },
  }
}

function ActionControl({
  action,
  running,
  primary,
}: {
  action: Action
  running: Running
  primary: boolean
}): ReactElement {
  const variant = primary ? 'primary' : 'secondary'
  const size = primary ? 'md' : 'sm'

  if (action.kind === 'link') {
    return (
      <ButtonLink
        to={action.to}
        variant={variant}
        size={size}
        icon={action.icon}
        aria-label={action.name}
      >
        {action.label}
      </ButtonLink>
    )
  }

  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      icon={action.kind === 'match' ? GitCompareArrowsIcon : MessagesSquareIcon}
      aria-label={action.name}
      disabled={running.busy}
      onClick={() => {
        running.run(action)
      }}
    >
      {action.label}
    </Button>
  )
}

/** The wait and the failure of a step's action, shown under that step. */
function ActionState({
  action,
  running,
}: {
  action: Action
  running: Running
}): ReactElement | null {
  if (action.kind === 'link') {
    return null
  }

  const error = running.errorFor(action.pairing)

  return (
    <>
      {running.pendingFor(action.pairing) ? (
        <Thinking>
          {action.kind === 'match' ? 'Matching your resume…' : 'Preparing questions…'}
        </Thinking>
      ) : null}
      {error ? <Alert>{error.message}</Alert> : null}
    </>
  )
}

/** What the best match found missing, as stamps, cut short when long. */
function Gaps({ gaps }: { gaps: string[] }): ReactElement {
  const shown = gaps.slice(0, GAPS_SHOWN)
  const more = gaps.length - shown.length

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-sm text-ink-soft">Missing from your resume:</span>
      {shown.map((gap) => (
        <Chip key={gap} present={false}>
          {gap}
        </Chip>
      ))}
      {more > 0 ? (
        <span className="text-sm text-ink-soft">and {String(more)} more</span>
      ) : null}
    </div>
  )
}

/**
 * The next step, as the file of the posting it is about: its title on the
 * tab, the path of the application across the top, then the sentence and the
 * one primary action on the page.
 */
function NextStep({ step, running }: { step: Step; running: Running }): ReactElement {
  const { sentence, detail, action } = describe(step)
  const place = placeOf(step)

  return (
    <section aria-labelledby="next-step">
      <Sheet tab={place?.title} className="flex flex-col items-start gap-4">
        {place ? (
          <div className="self-stretch">
            <StageRail reached={place.reached} score={place.score} />
          </div>
        ) : null}
        <div className="flex max-w-prose flex-col gap-1">
          <h2
            id="next-step"
            className="text-[1.75rem] leading-tight font-extrabold tracking-tight"
          >
            {sentence}
          </h2>
          {detail ? <p className="text-ink-soft">{detail}</p> : null}
        </div>
        {place && place.gaps.length > 0 ? <Gaps gaps={place.gaps} /> : null}
        <ActionControl action={action} running={running} primary />
        <ActionState action={action} running={running} />
      </Sheet>
    </section>
  )
}

function OtherSteps({
  steps,
  running,
}: {
  steps: Step[]
  running: Running
}): ReactElement | null {
  if (steps.length === 0) {
    return null
  }

  return (
    <section aria-labelledby="other-steps" className="flex flex-col gap-3">
      <h3 id="other-steps" className="text-lg font-bold">
        Other things to do
      </h3>
      <Sheet>
        <ul className="flex flex-col divide-y divide-line">
          {steps.map((step) => {
            const { sentence, detail, action } = describe(step)
            const place = placeOf(step)

            return (
              <li key={keyOf(step)} className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                  {place ? <StageRail reached={place.reached} compact /> : null}
                  <div className="min-w-48 flex-1">
                    <p className="font-semibold">{sentence}</p>
                    {detail ? <p className="text-sm text-ink-soft">{detail}</p> : null}
                  </div>
                  <ActionControl action={action} running={running} primary={false} />
                </div>
                <ActionState action={action} running={running} />
              </li>
            )
          })}
        </ul>
      </Sheet>
    </section>
  )
}

/**
 * Your last few matches and interviews, as on History.
 *
 * Nothing while it loads and nothing for an account without history: it is
 * the quiet part of the page, and a skeleton here would pull the eye away
 * from the next step.
 */
function Recently(): ReactElement | null {
  const matches = useMatches(RECENT)
  const interviews = useInterviews(RECENT)
  const error = matches.error ?? interviews.error
  const rows = newestFirst(matches.data ?? [], interviews.data ?? []).slice(0, RECENT)

  if (!error && rows.length === 0) {
    return null
  }

  return (
    <section aria-labelledby="recently" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="recently" className="text-lg font-bold">
          Recently
        </h3>
        <ButtonLink to="/history" variant="quiet" size="sm">
          See all history
        </ButtonLink>
      </div>

      {error ? (
        <Alert
          onRetry={() => {
            void matches.refetch()
            void interviews.refetch()
          }}
        >
          {error.message}
        </Alert>
      ) : (
        <Sheet>
          <ul className="flex flex-col divide-y divide-line">
            {rows.map((row) => (
              <li
                key={row.key}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 first:pt-0 last:pb-0"
              >
                <row.icon aria-hidden="true" className="size-4 shrink-0 text-ink-faint" />
                <Link to={row.to} className="min-w-0 flex-1 hover:text-accent hover:underline">
                  {row.what}{' '}
                  {row.score === null ? (
                    <span className="font-semibold">{row.outcome}</span>
                  ) : (
                    <Score value={row.score} size="sm" />
                  )}
                  {' — '}
                  {row.title}
                </Link>
                <time
                  dateTime={row.at}
                  title={new Date(row.at).toLocaleString()}
                  className="text-sm text-ink-faint"
                >
                  {ago(row.at)}
                </time>
              </li>
            ))}
          </ul>
        </Sheet>
      )}
    </section>
  )
}

/**
 * The home page: what to do next.
 *
 * One step leads, in a sentence, with the only primary action on the page;
 * the others wait underneath, and recent work sits at the bottom. The steps
 * come from the API in order and never empty, so there is no empty state.
 */
export function Dashboard(): ReactElement {
  const dashboard = useDashboard()
  const running = useRunning()

  if (dashboard.isPending) {
    return <Skeleton lines={3} label="Working out what to do next…" />
  }

  if (dashboard.isError) {
    return (
      <Alert
        onRetry={() => {
          void dashboard.refetch()
        }}
      >
        {dashboard.error.message}
      </Alert>
    )
  }

  const [next, ...others] = dashboard.data

  return (
    <>
      {next ? <NextStep step={next} running={running} /> : null}
      <OtherSteps steps={others} running={running} />
      <Recently />
    </>
  )
}
