import type { ReactElement } from 'react'
import { ArrowLeftIcon, MessagesSquareIcon } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router'

import { useStartInterview } from '../api/interview'
import type { Match } from '../api/matching'
import { useMatchDetail } from '../api/matching'
import { Alert, Button, Muted, Skeleton, Thinking } from '../ui'
import { MatchResult } from './MatchResult'

const BACK = 'inline-flex items-center gap-1 text-sm text-ink-soft hover:text-accent'

/**
 * Where "back" goes from a result: to the posting it was run against, or to
 * History when that posting has since been deleted (the match is a snapshot
 * and outlives it).
 */
export function BackToPosting({
  documentId,
  title,
}: {
  documentId: string | null
  title: string | null
}): ReactElement {
  return (
    <p>
      <Link
        to={documentId ? `/documents/${documentId}` : '/history'}
        className={BACK}
      >
        <ArrowLeftIcon aria-hidden="true" className="size-4" />
        {documentId ? (title ?? 'The posting') : 'History'}
      </Link>
    </p>
  )
}

/**
 * The next step after a match: practising the interview on the same pair.
 * Only while both halves still exist -- a snapshot can outlive its resume or
 * posting, and an interview needs them.
 */
function Practise({ match }: { match: Match }): ReactElement {
  const start = useStartInterview()
  const navigate = useNavigate()
  const { resume_id: resumeId, document_id: documentId } = match
  const pairGone = !resumeId || !documentId

  return (
    <div className="flex flex-col items-start gap-2">
      <Button
        type="button"
        icon={MessagesSquareIcon}
        disabled={pairGone || start.isPending}
        onClick={() => {
          if (resumeId && documentId) {
            start.mutate(
              { resumeId, documentId },
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
      {pairGone ? (
        <Muted>
          The resume or the posting this match used has been deleted, so there is
          nothing to practise on.
        </Muted>
      ) : null}
      {start.isPending ? <Thinking>Preparing questions…</Thinking> : null}
      {start.error ? <Alert>{start.error.message}</Alert> : null}
    </div>
  )
}

/** One stored match, shown exactly as a fresh one is, with the way onwards. */
export function MatchDetail(): ReactElement {
  const { matchId = '' } = useParams()
  const match = useMatchDetail(matchId)

  return (
    <>
      {match.data ? (
        <BackToPosting
          documentId={match.data.document_id}
          title={match.data.document_title ?? null}
        />
      ) : (
        <BackToPosting documentId={null} title={null} />
      )}

      {match.isPending ? <Skeleton lines={2} label="Loading the match…" /> : null}
      {match.error ? <Alert>{match.error.message}</Alert> : null}
      {match.data ? (
        <>
          <MatchResult match={match.data} />
          <Practise match={match.data} />
        </>
      ) : null}
    </>
  )
}
