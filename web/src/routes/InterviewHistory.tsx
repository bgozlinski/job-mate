import { useState } from 'react'
import type { ReactElement } from 'react'
import { Link } from 'react-router'

import {
  INTERVIEWS_PAGE_SIZE,
  MAX_INTERVIEWS_PAGE_SIZE,
  useInterviews,
} from '../api/interview'
import type { InterviewSummary } from '../api/interview'
import { Alert, Button, Card, Muted, PageTitle } from '../ui'
import { percentage } from './MatchResult'

function outcome(interview: InterviewSummary): string {
  if (interview.status === 'active') {
    return 'In progress'
  }

  return interview.score === null ? 'Finished, nothing judged' : percentage(interview.score)
}

/** The caller's own interviews, newest first; an unfinished one can be resumed. */
export function InterviewHistory(): ReactElement {
  const [shown, setShown] = useState(INTERVIEWS_PAGE_SIZE)
  const interviews = useInterviews(shown)

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <PageTitle>Your interviews</PageTitle>
          <Muted>Only yours: nobody else can read your interviews.</Muted>
        </div>
        <Link to="/interview" className="text-sm text-accent hover:underline">
          Start a new interview
        </Link>
      </div>

      {interviews.isPending ? <Muted>Loading…</Muted> : null}
      {interviews.error ? <Alert>{interviews.error.message}</Alert> : null}
      {interviews.data?.length === 0 ? <Muted>No interviews yet.</Muted> : null}

      <ul className="flex flex-col gap-3">
        {interviews.data?.map((interview) => (
          <li key={interview.id}>
            <Card className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <Link
                to={`/interviews/${interview.id}`}
                className="text-base font-medium text-accent hover:underline"
              >
                {outcome(interview)} · {interview.document_title ?? 'Untitled posting'}
              </Link>
              <p className="text-sm text-ink-faint">
                <time dateTime={interview.created_at}>
                  {new Date(interview.created_at).toLocaleString()}
                </time>
                {' · '}
                <span>{String(interview.question_count)} questions planned</span>
              </p>
            </Card>
          </li>
        ))}
      </ul>

      {/* A short page is the end of the listing: the route returns no total. */}
      {interviews.data && interviews.data.length >= shown ? (
        shown >= MAX_INTERVIEWS_PAGE_SIZE ? (
          <Muted>The list returns at most {MAX_INTERVIEWS_PAGE_SIZE} interviews.</Muted>
        ) : (
          <div className="flex">
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setShown((current) =>
                  Math.min(current + INTERVIEWS_PAGE_SIZE, MAX_INTERVIEWS_PAGE_SIZE),
                )
              }}
            >
              Load more
            </Button>
          </div>
        )
      ) : null}
    </>
  )
}
