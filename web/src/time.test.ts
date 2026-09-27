import { expect, test } from 'vitest'

import { ago, day, today } from './time'

const NOW = new Date('2026-09-25T12:00:00Z').getTime()

test.each([
  ['2026-09-25T08:00:00Z', 'today'],
  ['2026-09-24T12:00:00Z', 'yesterday'],
  ['2026-09-22T12:00:00Z', '3 days ago'],
  ['2026-09-11T12:00:00Z', '2 weeks ago'],
  ['2026-06-20T12:00:00Z', '3 months ago'],
  ['2024-09-01T12:00:00Z', '2 years ago'],
])('%s reads as %s', (iso, words) => {
  expect(ago(iso, NOW)).toBe(words)
})

test('a clock slightly behind the server does not say "in 1 day"', () => {
  expect(ago('2026-09-25T12:30:00Z', NOW)).toBe('today')
})

test('a day is shown as that day, whatever the time zone', () => {
  // Built and formatted in UTC: new Date('2026-09-20') would be the 19th in
  // any zone west of Greenwich.
  expect(day('2026-09-20')).toBe('Sep 20, 2026')
  expect(day('2026-01-01')).toBe('Jan 1, 2026')
})

test('today is the reader’s day, not the one in UTC', () => {
  // Late in the evening, local time: UTC may have moved on, the reader has not.
  expect(today(new Date(2026, 8, 20, 23, 30))).toBe('2026-09-20')
  expect(today(new Date(2026, 0, 5, 0, 5))).toBe('2026-01-05')
})
