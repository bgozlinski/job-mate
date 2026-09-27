import type { ReactElement } from 'react'
import { HistoryIcon } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'

import { pageCount } from '../api/documents'
import { HISTORY_PAGE_SIZE, useHistory } from '../api/history'
import type { HistoryItem, HistoryKind } from '../api/history'
import {
  Alert,
  Button,
  EmptyState,
  Notice,
  PageHeader,
  Pagination,
  Sheet,
  Skeleton,
  pageFrom,
} from '../ui'
import { TimelineItem } from './TimelineItem'
import { fromInterview, fromMatch } from './timeline'
import type { Row } from './timeline'

const FILTERS: { kind: HistoryKind; label: string }[] = [
  { kind: 'all', label: 'All' },
  { kind: 'matches', label: 'Matches' },
  { kind: 'interviews', label: 'Interviews' },
]

function kindOf(value: string | null): HistoryKind {
  return value === 'matches' || value === 'interviews' ? value : 'all'
}

/** The address of one page of one kind of history; page 1 and "all" are bare. */
function historyHref(kind: HistoryKind, page: number): string {
  const query = new URLSearchParams()

  if (kind !== 'all') {
    query.set('kind', kind)
  }

  if (page > 1) {
    query.set('page', String(page))
  }

  const search = query.toString()

  return search ? `/history?${search}` : '/history'
}

/** One line of the history, whichever of the two it is. */
function rowOf(item: HistoryItem): Row | null {
  if (item.kind === 'match' && item.match) {
    return fromMatch(item.match)
  }

  if (item.kind === 'interview' && item.interview) {
    return fromInterview(item.interview)
  }

  return null
}

/**
 * Everything you did, newest first: matches and interviews on one timeline,
 * a numbered page at a time.
 *
 * The API merges the two before it pages them, since page 3 of the timeline
 * is not page 3 of each list. The kind and the page live in the address, so a
 * reload or "back" returns to the same place; picking a kind starts at its
 * first page.
 */
export function History(): ReactElement {
  const [params, setParams] = useSearchParams()
  const kind = kindOf(params.get('kind'))
  const page = pageFrom(params.get('page'))
  const history = useHistory(kind, page)
  const rows = (history.data?.items ?? [])
    .map(rowOf)
    .filter((row): row is Row => row !== null)
  const total = history.data?.total ?? 0
  const pages = pageCount(total, HISTORY_PAGE_SIZE)
  const pastEnd = history.isSuccess && total > 0 && rows.length === 0

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

      {history.isPending ? <Skeleton lines={3} label="Loading your history…" /> : null}
      {history.error ? (
        <Alert
          onRetry={() => {
            void history.refetch()
          }}
        >
          {history.error.message}
        </Alert>
      ) : null}

      {history.isSuccess && total === 0 ? (
        <EmptyState icon={HistoryIcon} title="Nothing here yet.">
          Open a posting to match your CV against it or practise its interview.
        </EmptyState>
      ) : null}

      {pastEnd ? (
        <Notice>
          There is no page {page} of this history.{' '}
          <Link
            to={historyHref(kind, pages)}
            className="text-accent underline underline-offset-2"
          >
            Go to the last page
          </Link>
          .
        </Notice>
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

      <Pagination
        page={page}
        count={pages}
        hrefFor={(n) => historyHref(kind, n)}
        label="Pages of history"
      />
    </>
  )
}
