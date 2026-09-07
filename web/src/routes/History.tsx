import { useState } from 'react'
import type { ReactElement } from 'react'
import { Link, useParams } from 'react-router'

import {
  HISTORY_PAGE_SIZE,
  MAX_HISTORY_PAGE_SIZE,
  useMatchDetail,
  useMatches,
} from '../api/matching'
import { MatchResult, percentage } from './MatchResult'

/** The caller's own past matches, newest first (FR-2). */
export function History(): ReactElement {
  const [shown, setShown] = useState(HISTORY_PAGE_SIZE)
  const matches = useMatches(shown)

  return (
    <>
      <h2>Match history</h2>
      <p>Only yours: nobody else can read your matches.</p>

      {matches.isPending ? <p>Loading…</p> : null}
      {matches.error ? <p role="alert">{matches.error.message}</p> : null}
      {matches.data?.length === 0 ? <p>No matches yet.</p> : null}

      <ul>
        {matches.data?.map((match) => (
          <li key={match.id}>
            <Link to={`/matches/${match.id}`}>
              {percentage(match.score)} · {match.document_title ?? 'Untitled posting'}
            </Link>
            <p>
              <time dateTime={match.created_at}>
                {new Date(match.created_at).toLocaleString()}
              </time>
              {' · '}
              <span>
                {String(match.matched_count)} covered,{' '}
                {String(match.missing_count)} missing
              </span>
            </p>
          </li>
        ))}
      </ul>

      {/* A short page is the end of the listing: the route returns no total. */}
      {matches.data && matches.data.length >= shown ? (
        shown >= MAX_HISTORY_PAGE_SIZE ? (
          <p>The history returns at most {MAX_HISTORY_PAGE_SIZE} matches.</p>
        ) : (
          <button
            type="button"
            onClick={() => {
              setShown((current) =>
                Math.min(current + HISTORY_PAGE_SIZE, MAX_HISTORY_PAGE_SIZE),
              )
            }}
          >
            Load more
          </button>
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
        <Link to="/matches">Back to the history</Link>
      </p>

      {match.isPending ? <p>Loading…</p> : null}
      {match.error ? <p role="alert">{match.error.message}</p> : null}
      {match.data ? <MatchResult match={match.data} /> : null}
    </>
  )
}
