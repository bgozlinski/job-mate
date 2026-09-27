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

const DAY_FORMAT = new Intl.DateTimeFormat('en', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  timeZone: 'UTC',
})

/**
 * A calendar day from the API ("2026-09-20") as a person reads it: "Sep 20, 2026".
 *
 * Never through `new Date("2026-09-20")`: that is midnight UTC, which is the
 * 19th anywhere west of Greenwich. The day is built in UTC and formatted in
 * UTC, so it is the same day wherever the page is open.
 */
export function day(iso: string): string {
  const [year = 0, month = 1, date = 1] = iso.split('-').map(Number)

  return DAY_FORMAT.format(Date.UTC(year, month - 1, date))
}

/** When a timestamp happened, as the calendar day where the reader is. */
export function dayOf(timestamp: string): string {
  return new Date(timestamp).toLocaleDateString('en', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

/**
 * Today where the reader is, as the API writes a day ("2026-09-20").
 *
 * Not `toISOString()`, which is the day in UTC: after 22:00 in Warsaw that is
 * already tomorrow.
 */
export function today(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const date = String(now.getDate()).padStart(2, '0')

  return `${String(now.getFullYear())}-${month}-${date}`
}
