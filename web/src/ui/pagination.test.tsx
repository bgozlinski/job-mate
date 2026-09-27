import { expect, test } from 'vitest'

import { pageFrom, pageKeeping, pagedSearch, pagesAround, sizeFrom, steps } from '.'
import type { Step } from '.'

test.each([
  [1, 1, [1]],
  [2, 3, [1, 2, 3]],
  [1, 12, [1, 2, null, 12]],
  [5, 12, [1, null, 4, 5, 6, null, 12]],
  [12, 12, [1, null, 11, 12]],
  [3, 5, [1, 2, 3, 4, 5]],
])('page %i of %i shows %j', (page, count, shown) => {
  expect(pagesAround(page, count)).toEqual(shown)
})

test.each([
  [null, 1],
  ['3', 3],
  ['0', 1],
  ['-2', 1],
  ['2.5', 1],
  ['two', 1],
])('the address %j asks for page %i', (value, page) => {
  expect(pageFrom(value)).toBe(page)
})

test.each([
  [null, 20],
  ['10', 10],
  ['5', 5],
  ['1000', 20],
  ['7', 20],
  ['abc', 20],
])('the address %j asks for pages of %i', (value, size) => {
  expect(sizeFrom(value)).toBe(size)
})

test.each([
  [7, 5, 20, 2],
  [1, 20, 5, 1],
  [2, 20, 5, 5],
  [3, 10, 15, 2],
])('page %i of %i-row pages, shown %i a page, is page %i', (page, from, to, kept) => {
  expect(pageKeeping(page, from, to)).toBe(kept)
})

test('only what differs from the defaults reaches the address', () => {
  expect(pagedSearch(1, 20)).toBe('')
  expect(pagedSearch(3, 20)).toBe('?page=3')
  expect(pagedSearch(1, 10)).toBe('?size=10')
  expect(pagedSearch(2, 5, { kind: 'matches' })).toBe('?kind=matches&page=2&size=5')
})

/** The row as each width draws it: numbers, and "…" for a gap. */
function drawn(row: Step[], at: 'narrow' | 'wide'): string {
  return row
    .filter((step) => step[at])
    .map((step) => (step.page === null ? '…' : String(step.page)))
    .join(' ')
}

test.each([
  [5, 12, '1 … 5 … 12', '1 … 4 5 6 … 12'],
  [3, 12, '1 … 3 … 12', '1 2 3 4 … 12'],
  [2, 12, '1 2 … 12', '1 2 3 … 12'],
  [1, 3, '1 … 3', '1 2 3'],
  [12, 12, '1 … 12', '1 … 11 12'],
])('page %i of %i reads "%s" on a phone and "%s" wider', (page, count, narrow, wide) => {
  const row = steps(page, count)

  expect(drawn(row, 'narrow')).toBe(narrow)
  expect(drawn(row, 'wide')).toBe(wide)
  // Each page once, whatever the width: one link per page to a screen reader.
  const pages = row.filter((step) => step.page !== null).map((step) => step.page)
  expect(new Set(pages).size).toBe(pages.length)
})
