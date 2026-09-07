import { useState } from 'react'
import type { ReactElement } from 'react'
import { Link, useParams } from 'react-router'

import {
  HISTORY_PAGE_SIZE,
  MAX_HISTORY_PAGE_SIZE,
  useMatchDetail,
  useMatches,
} from '../api/matching'
import { Alert, Button, Card, Muted, PageTitle } from '../ui'
import { MatchResult, percentage } from './MatchResult'

/** The caller's own past matches, newest first (FR-2). */
export function History(): ReactElement {
  const [shown, setShown] = useState(HISTORY_PAGE_SIZE)
  const matches = useMatches(shown)

  return (
    <>
      <div>
        <PageTitle>Match history</PageTitle>
        <Muted>Only yours: nobody else can read your matches.</Muted>
      </div>

      {matches.isPending ? <Muted>Loading…</Muted> : null}
      {matches.error ? <Alert>{matches.error.message}</Alert> : null}
      {matches.data?.length === 0 ? <Muted>No matches yet.</Muted> : null}

      <ul className="flex flex-col gap-3">
        {matches.data?.map((match) => (
          <li key={match.id}>
            <Card className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <Link
                to={`/matches/${match.id}`}
                className="text-base font-medium text-accent hover:underline"
              >
                {percentage(match.score)} ·{' '}
                {match.document_title ?? 'Untitled posting'}
              </Link>
              <p className="text-sm text-ink-faint">
                <time dateTime={match.created_at}>
                  {new Date(match.created_at).toLocaleString()}
                </time>
                {' · '}
                <span>
                  {String(match.matched_count)} covered,{' '}
                  {String(match.missing_count)} missing
                </span>
              </p>
            </Card>
          </li>
        ))}
      </ul>

      {/* A short page is the end of the listing: the route returns no total. */}
      {matches.data && matches.data.length >= shown ? (
        shown >= MAX_HISTORY_PAGE_SIZE ? (
          <Muted>
            The history returns at most {MAX_HISTORY_PAGE_SIZE} matches.
          </Muted>
        ) : (
          <div className="flex">
            <Button
              type="button"
              variant="secondary"
              onClick={() => {
                setShown((current) =>
                  Math.min(current + HISTORY_PAGE_SIZE, MAX_HISTORY_PAGE_SIZE),
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

/** One stored match, shown exactly as a fresh one is. */
export function MatchDetail(): ReactElement {
  const { matchId } = useParams()
  const match = useMatchDetail(matchId ?? '')

  return (
    <>
      <p>
        <Link
          to="/matches"
          className="text-sm text-ink-soft hover:text-accent"
        >
          ← Back to the history
        </Link>
      </p>

      {match.isPending ? <Muted>Loading…</Muted> : null}
      {match.error ? <Alert>{match.error.message}</Alert> : null}
      {match.data ? <MatchResult match={match.data} /> : null}
    </>
  )
}
