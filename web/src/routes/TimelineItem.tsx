import type { ReactElement } from 'react'
import { Link } from 'react-router'

import { ago } from '../time'
import { Score } from '../ui'
import type { Row } from './timeline'

/**
 * One match or interview in your history, the same on History and on the
 * dashboard: what it was, how it went, on which posting -- a sentence, not
 * fields joined by dots -- and how long ago, with the exact time on hover.
 */
export function TimelineItem({ row }: { row: Row }): ReactElement {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 first:pt-0 last:pb-0">
      <row.icon aria-hidden="true" className="size-4 shrink-0 text-ink-faint" />
      <Link to={row.to} className="min-w-48 flex-1 hover:text-accent hover:underline">
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
  )
}
