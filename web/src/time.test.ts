import { expect, test } from 'vitest'

import { ago } from './time'

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
