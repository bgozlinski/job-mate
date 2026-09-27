import { expect, test } from 'vitest'

import { pageFrom, pagesAround } from '.'

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
