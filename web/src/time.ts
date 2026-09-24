const DAY = 24 * 60 * 60 * 1000

const relative = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

/**
 * How long ago something happened, in the words a list row can afford:
 * "today", "yesterday", "3 days ago", "2 weeks ago", "5 months ago".
 *
 * Whole days, not hours: a posting added this morning and one added an hour
 * ago are the same age to someone choosing which to apply for. The exact time
 * stays on the element's title and dateTime.
 */
export function ago(iso: string, now: number = Date.now()): string {
  const days = Math.floor((now - new Date(iso).getTime()) / DAY)

  if (days < 7) {
    return relative.format(-Math.max(days, 0), 'day')
  }

  if (days < 30) {
    return relative.format(-Math.floor(days / 7), 'week')
  }

  if (days < 365) {
    return relative.format(-Math.floor(days / 30), 'month')
  }

  return relative.format(-Math.floor(days / 365), 'year')
}
