import { GitCompareArrowsIcon, MessagesSquareIcon } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import type { InterviewSummary } from '../api/interview'
import type { MatchSummary } from '../api/matching'
import { percentage } from '../ui'

/**
 * One match or interview as a line of your history, drawn the same way on
 * History and on the dashboard's "Recently".
 */
export interface Row {
  key: string
  to: string
  icon: LucideIcon
  what: string
  outcome: string
  title: string
  at: string
}

export function fromMatch(match: MatchSummary): Row {
  return {
    key: `m-${match.id}`,
    to: `/matches/${match.id}`,
    icon: GitCompareArrowsIcon,
    what: 'Match',
    outcome: percentage(match.score),
    title: match.document_title ?? 'Deleted posting',
    at: match.created_at,
  }
}

export function fromInterview(interview: InterviewSummary): Row {
  return {
    key: `i-${interview.id}`,
    to: `/interviews/${interview.id}`,
    icon: MessagesSquareIcon,
    what: 'Interview',
    outcome:
      interview.status === 'active'
        ? 'In progress'
        : interview.score === null
          ? 'Finished, nothing judged'
          : percentage(interview.score),
    title: interview.document_title ?? 'Deleted posting',
    at: interview.created_at,
  }
}

/** Matches and interviews on one timeline, newest first. */
export function newestFirst(
  matches: readonly MatchSummary[],
  interviews: readonly InterviewSummary[],
): Row[] {
  return [...matches.map(fromMatch), ...interviews.map(fromInterview)].sort((a, b) =>
    a.at < b.at ? 1 : a.at > b.at ? -1 : 0,
  )
}
