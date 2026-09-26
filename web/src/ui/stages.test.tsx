import { render, screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'

import { Chip, Score, StageRail, reachedOf } from '.'

function steps() {
  return within(screen.getByRole('list', { name: 'Stage' })).getAllByRole('listitem')
}

test('the stages are the four steps of an application, in order', () => {
  render(<StageRail reached={1} />)

  expect(steps().map((step) => step.textContent)).toEqual([
    expect.stringContaining('Posting'),
    expect.stringContaining('Match'),
    expect.stringContaining('Interview'),
    expect.stringContaining('Applied'),
  ])
})

test.each([
  [1, 'Match'],
  [2, 'Interview'],
])('having reached stage %i, the next step is %s', (reached, next) => {
  render(<StageRail reached={reached as 1 | 2} />)

  const current = steps().filter((step) => step.getAttribute('aria-current') === 'step')
  expect(current).toHaveLength(1)
  expect(current[0]).toHaveTextContent(next)
})

test('after an interview nothing is next until applications can be tracked', () => {
  render(<StageRail reached={3} />)

  expect(steps().some((step) => step.hasAttribute('aria-current'))).toBe(false)
  expect(steps()[3]).toHaveTextContent('coming later')
})

test('each step says whether it is done', () => {
  render(<StageRail reached={2} />)

  const [posting, match, interview] = steps()
  expect(posting).toHaveTextContent('done')
  expect(match).toHaveTextContent('done')
  expect(interview).toHaveTextContent('not yet')
})

test('the match step carries its score', () => {
  render(<StageRail reached={2} score={0.72} />)

  expect(steps()[1]).toHaveTextContent('72%')
})

test('the compact rail is one sentence to a screen reader', () => {
  render(<StageRail reached={2} compact />)

  expect(screen.getByText('Stage 2 of 4: Match')).toBeInTheDocument()
  expect(screen.queryByRole('list')).not.toBeInTheDocument()
})

test('a missing requirement is marked by more than its colour', () => {
  render(<Chip present={false}>Kubernetes</Chip>)

  const chip = screen.getByText('Kubernetes')
  expect(chip.querySelector('svg')).not.toBeNull()
})

test('a score reads as a percentage', () => {
  render(<Score value={0.72} size="lg" />)

  expect(screen.getByText('72%')).toBeInTheDocument()
})

test('a stage outside what the rail can draw is clamped, not cast', () => {
  expect([0, 1, 2, 3, 4].map(reachedOf)).toEqual([1, 1, 2, 3, 3])
})
