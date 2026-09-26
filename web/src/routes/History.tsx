import { useState } from 'react'
import type { ReactElement } from 'react'
import { HistoryIcon } from 'lucide-react'
import { useSearchParams } from 'react-router'

import { useInterviews } from '../api/interview'
import { HISTORY_PAGE_SIZE, MAX_HISTORY_PAGE_SIZE, useMatches } from '../api/matching'
import { Alert, Button, EmptyState, PageHeader, Sheet, Skeleton } from '../ui'
import { TimelineItem } from './TimelineItem'
import { newestFirst } from './timeline'

type Kind = 'all' | 'matches' | 'interviews'

const FILTERS: { kind: Kind; label: string }[] = [
  { kind: 'all', label: 'All' },
  { kind: 'matches', label: 'Matches' },
  { kind: 'interviews', label: 'Interviews' },
]

function kindOf(value: string | null): Kind {
  return value === 'matches' || value === 'interviews' ? value : 'all'
}

/**
 * Everything you did, newest first: matches and interviews on one timeline.
 *
 * Two lists read from the top with the same growing limit, merged here. Each
 * is fetched from offset 0, as the old histories were: a new row lands above
 * the page, so paging by offset would show one row twice.
 */
export function History(): ReactElement {
  const [params, setParams] = useSearchParams()
  const kind = kindOf(params.get('kind'))
  const [shown, setShown] = useState(HISTORY_PAGE_SIZE)
  const matches = useMatches(shown)
  const interviews = useInterviews(shown)

  const rows = newestFirst(
    kind === 'interviews' ? [] : (matches.data ?? []),
    kind === 'matches' ? [] : (interviews.data ?? []),
  )

  const pending =
    (kind !== 'interviews' && matches.isPending) ||
    (kind !== 'matches' && interviews.isPending)
  const error = matches.error ?? interviews.error
  // A full page from either list means that list may have more; the API gives
  // no total, so a short page is how the end shows.
  const more =
    (kind !== 'interviews' && (matches.data?.length ?? 0) >= shown) ||
    (kind !== 'matches' && (interviews.data?.length ?? 0) >= shown)

  return (
    <>
      <PageHeader
        title="History"
        description="Your matches and interviews, newest first. Only yours: nobody else can read them."
      />

      <div role="group" aria-label="Show" className="flex flex-wrap gap-1">
        {FILTERS.map((filter) => (
          <Button
            key={filter.kind}
            type="button"
            size="sm"
            variant={kind === filter.kind ? 'primary' : 'secondary'}
            aria-pressed={kind === filter.kind}
            onClick={() => {
              setParams(filter.kind === 'all' ? {} : { kind: filter.kind })
            }}
          >
            {filter.label}
          </Button>
        ))}
      </div>

      {pending ? <Skeleton lines={3} label="Loading your history…" /> : null}
      {error ? (
        <Alert
          onRetry={() => {
            // Both, whichever failed: asking the healthy one again costs a
            // cheap read and keeps the timeline from mixing old and new rows.
            void matches.refetch()
            void interviews.refetch()
          }}
        >
          {error.message}
        </Alert>
      ) : null}

      {!pending && !error && rows.length === 0 ? (
        <EmptyState icon={HistoryIcon} title="Nothing here yet.">
          Open a posting to match your CV against it or practise its interview.
        </EmptyState>
      ) : null}

      {rows.length > 0 ? (
        <Sheet>
          <ul className="flex flex-col divide-y divide-line">
            {rows.map((row) => (
              <TimelineItem key={row.key} row={row} />
            ))}
          </ul>
        </Sheet>
      ) : null}

      {more ? (
        shown >= MAX_HISTORY_PAGE_SIZE ? (
          <p className="text-sm text-ink-faint">
            History shows at most {MAX_HISTORY_PAGE_SIZE} of each.
          </p>
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
