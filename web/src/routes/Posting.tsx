import { useState } from 'react'
import type { ReactElement } from 'react'
import {
  ArrowLeftIcon,
  GitCompareArrowsIcon,
  MessagesSquareIcon,
} from 'lucide-react'
import { Link, useLocation, useNavigate, useParams } from 'react-router'

import { useDocument } from '../api/documents'
import type { DocumentDetail } from '../api/documents'
import { usePostingInterviews, useStartInterview } from '../api/interview'
import { PER_POSTING, usePostingMatches, useMatch } from '../api/matching'
import { useResumes } from '../api/resumes'
import type { Resume } from '../api/resumes'
import {
  Alert,
  Button,
  CONTROL,
  EmptyState,
  PageHeader,
  Sheet,
  Skeleton,
  Status,
  Thinking,
  percentage,
} from '../ui'

const LINK = 'text-accent underline underline-offset-2'
const HEADING = 'text-xs font-bold tracking-wide text-ink-soft uppercase'
const BACK = 'inline-flex items-center gap-1 text-sm text-ink-soft hover:text-accent'

/** What an ingestion hands over when it opens the posting it stored. */
export interface Arrival {
  duplicate: boolean
}

/**
 * The resume a posting's actions use unless another is picked: the newest.
 * The person has one main resume, and asking every time would be a step with
 * one sensible answer.
 */
export function newest(resumes: Resume[]): Resume | undefined {
  return resumes.reduce<Resume | undefined>(
    (latest, resume) =>
      latest === undefined || resume.created_at > latest.created_at ? resume : latest,
    undefined,
  )
}

function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString()
}

/**
 * Match my CV and Practise interview, over one chosen resume.
 *
 * Both wait several seconds on a model, so while one runs both are off and a
 * sentence says what is happening -- a person who sees nothing move presses
 * again. Each lands on its own page when done.
 */
function Actions({ posting }: { posting: DocumentDetail }): ReactElement {
  const resumes = useResumes()
  const match = useMatch()
  const start = useStartInterview()
  const navigate = useNavigate()
  const [picked, setPicked] = useState('')

  const available = resumes.data ?? []
  const resumeId = picked || newest(available)?.id
  const busy = match.isPending || start.isPending
  const noResume = resumes.isSuccess && available.length === 0
  const noRequirements = !posting.requirements || posting.requirements.length === 0

  return (
    <div className="flex flex-col items-start gap-2 sm:items-end">
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          icon={GitCompareArrowsIcon}
          disabled={busy || !resumeId}
          onClick={() => {
            if (resumeId) {
              match.mutate(
                { resumeId, documentId: posting.id },
                {
                  onSuccess: (result) => {
                    void navigate(`/matches/${result.id}`)
                  },
                },
              )
            }
          }}
        >
          Match my CV
        </Button>
        <Button
          type="button"
          variant="secondary"
          icon={MessagesSquareIcon}
          disabled={busy || !resumeId || noRequirements}
          onClick={() => {
            if (resumeId) {
              start.mutate(
                { resumeId, documentId: posting.id },
                {
                  onSuccess: (interview) => {
                    void navigate(`/interviews/${interview.id}`)
                  },
                },
              )
            }
          }}
        >
          Practise interview
        </Button>
      </div>

      {available.length > 0 ? (
        <label className="flex items-center gap-2 text-xs text-ink-faint">
          with
          <select
            aria-label="Resume"
            className={`${CONTROL} w-auto py-1 text-xs`}
            value={resumeId ?? ''}
            disabled={busy}
            onChange={(event) => {
              setPicked(event.target.value)
            }}
          >
            {available.map((resume) => (
              <option key={resume.id} value={resume.id}>
                {resume.original_filename ?? 'Pasted text'}
                {resume.target_role ? ` — ${resume.target_role}` : ''}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {noResume ? (
        <p className="text-sm text-ink-soft">
          <Link to="/resumes" className={LINK}>
            Add a resume first
          </Link>{' '}
          to match it or practise.
        </p>
      ) : null}

      {noRequirements && !noResume ? (
        <p className="max-w-xs text-xs text-ink-faint sm:text-right">
          An interview needs the posting&apos;s requirements, and these have not been
          read yet.
        </p>
      ) : null}

      {match.isPending ? <Thinking>Matching your CV…</Thinking> : null}
      {start.isPending ? <Thinking>Preparing questions…</Thinking> : null}
      {match.error ? <Alert>{match.error.message}</Alert> : null}
      {start.error ? <Alert>{start.error.message}</Alert> : null}
    </div>
  )
}

/**
 * The posting itself: what it asks for, then its text.
 *
 * The requirements are plain chips, not the covered/missing ones of a match:
 * nothing has been compared yet.
 */
function Details({ posting }: { posting: DocumentDetail }): ReactElement {
  const [expanded, setExpanded] = useState(false)
  const requirements = posting.requirements ?? []

  return (
    <Sheet className="flex flex-col gap-5">
      <section className="flex flex-col gap-2">
        <h3 className={HEADING}>Requirements ({requirements.length})</h3>
        {requirements.length > 0 ? (
          <ul className="flex flex-wrap gap-2">
            {requirements.map((requirement) => (
              <li
                key={requirement}
                className="rounded-control bg-sunken px-3 py-1 text-sm text-ink"
              >
                {requirement}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-ink-faint">
            Not read yet: requirements are read by a language model when a posting is
            added, and this one has none.
          </p>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h3 className={HEADING}>Posting</h3>
        <p
          className={`text-sm leading-relaxed whitespace-pre-line text-ink-soft ${expanded ? '' : 'line-clamp-6'}`}
        >
          {posting.content}
        </p>
        <div>
          <Button
            type="button"
            variant="quiet"
            size="sm"
            aria-expanded={expanded}
            onClick={() => {
              setExpanded((current) => !current)
            }}
          >
            {expanded ? 'Show less' : 'Show all'}
          </Button>
        </div>
      </section>
    </Sheet>
  )
}

function YourMatches({ documentId }: { documentId: string }): ReactElement {
  const matches = usePostingMatches(documentId)

  return (
    <Sheet className="flex flex-col gap-3">
      <h3 className={HEADING}>Your matches</h3>
      {matches.isPending ? <Skeleton lines={1} label="Loading your matches…" /> : null}
      {matches.error ? (
        <Alert
          onRetry={() => {
            void matches.refetch()
          }}
        >
          {matches.error.message}
        </Alert>
      ) : null}
      {matches.data?.length === 0 ? (
        <EmptyState icon={GitCompareArrowsIcon} title="No matches yet.">
          Match your CV to see how it covers this posting.
        </EmptyState>
      ) : null}
      {matches.data && matches.data.length > 0 ? (
        <>
          <ul className="flex flex-col gap-2">
            {matches.data.map((match) => (
              <li key={match.id} className="flex items-baseline gap-2 text-sm">
                <Link
                  to={`/matches/${match.id}`}
                  className="font-bold text-accent tabular-nums hover:underline"
                >
                  {percentage(match.score)}
                </Link>
                <time dateTime={match.created_at} className="text-ink-faint">
                  {formatDate(match.created_at)}
                </time>
              </li>
            ))}
          </ul>
          <Link
            to="/history?kind=matches"
            className="text-xs text-ink-soft hover:text-accent"
          >
            See all in History
          </Link>
        </>
      ) : null}
    </Sheet>
  )
}

function YourInterviews({ documentId }: { documentId: string }): ReactElement {
  const interviews = usePostingInterviews(documentId, PER_POSTING)

  return (
    <Sheet className="flex flex-col gap-3">
      <h3 className={HEADING}>Your interviews</h3>
      {interviews.isPending ? (
        <Skeleton lines={1} label="Loading your interviews…" />
      ) : null}
      {interviews.error ? (
        <Alert
          onRetry={() => {
            void interviews.refetch()
          }}
        >
          {interviews.error.message}
        </Alert>
      ) : null}
      {interviews.data?.length === 0 ? (
        <EmptyState icon={MessagesSquareIcon} title="No interviews yet.">
          Practise the questions this posting is likely to bring.
        </EmptyState>
      ) : null}
      {interviews.data && interviews.data.length > 0 ? (
        <>
          <ul className="flex flex-col gap-2">
            {interviews.data.map((interview) => (
              <li key={interview.id} className="flex items-baseline gap-2 text-sm">
                <Link
                  to={`/interviews/${interview.id}`}
                  className="font-bold text-accent tabular-nums hover:underline"
                >
                  {interview.status === 'active'
                    ? 'Continue'
                    : interview.score === null
                      ? 'Finished'
                      : percentage(interview.score)}
                </Link>
                <time dateTime={interview.created_at} className="text-ink-faint">
                  {formatDate(interview.created_at)}
                </time>
              </li>
            ))}
          </ul>
          <Link
            to="/history?kind=interviews"
            className="text-xs text-ink-soft hover:text-accent"
          >
            See all in History
          </Link>
        </>
      ) : null}
    </Sheet>
  )
}

/**
 * One posting: the centre of the work. What it asks for, what you did with it,
 * and the two things to do next -- match your CV, practise the interview.
 */
export function Posting(): ReactElement {
  const { documentId = '' } = useParams()
  const arrival = useLocation().state as Arrival | null
  const posting = useDocument(documentId)

  return (
    <>
      <p>
        <Link to="/documents" className={BACK}>
          <ArrowLeftIcon aria-hidden="true" className="size-4" />
          All postings
        </Link>
      </p>

      {posting.isPending ? <Skeleton lines={3} label="Loading the posting…" /> : null}
      {posting.error ? (
        <Alert
          onRetry={() => {
            void posting.refetch()
          }}
        >
          {posting.error.message}
        </Alert>
      ) : null}

      {posting.data ? (
        <>
          <PageHeader
            title={posting.data.title ?? 'Untitled posting'}
            description={
              <>
                {posting.data.source_url ? (
                  <>
                    <a
                      href={posting.data.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-accent hover:underline"
                    >
                      {hostOf(posting.data.source_url)}
                    </a>
                    {' · '}
                  </>
                ) : null}
                added {formatDate(posting.data.created_at)}
              </>
            }
            actions={<Actions posting={posting.data} />}
          />

          {arrival?.duplicate ? (
            <Status>
              This posting was already in the knowledge base, so nothing new was
              stored: here it is.
            </Status>
          ) : null}

          <div className="grid gap-6 md:grid-cols-[3fr_2fr]">
            <Details posting={posting.data} />
            <div className="flex flex-col gap-6">
              <YourMatches documentId={posting.data.id} />
              <YourInterviews documentId={posting.data.id} />
            </div>
          </div>
        </>
      ) : null}
    </>
  )
}
