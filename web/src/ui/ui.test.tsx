import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { Button, EmptyState, PageHeader, Skeleton, Spinner, Thinking } from '.'

test('a page header names the page and carries its actions', () => {
  render(
    <PageHeader
      title="Your interviews"
      description="Only yours."
      actions={<Button type="button">Start a new interview</Button>}
    />,
  )

  expect(screen.getByRole('heading', { name: 'Your interviews' })).toBeInTheDocument()
  expect(screen.getByText('Only yours.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Start a new interview' })).toBeInTheDocument()
})

test('an empty state says so and offers the way out', () => {
  render(
    <EmptyState title="No postings yet." action={<a href="/documents">Add one</a>}>
      Paste a job posting to match your resume against it.
    </EmptyState>,
  )

  expect(screen.getByText('No postings yet.')).toBeInTheDocument()
  expect(screen.getByText(/Paste a job posting/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Add one' })).toBeInTheDocument()
})

test('a skeleton is words to a screen reader, not grey blocks', () => {
  render(<Skeleton lines={2} label="Loading your resumes…" />)

  expect(screen.getByRole('status')).toHaveTextContent('Loading your resumes…')
  const blocks = screen.getAllByTestId('skeleton-block')
  expect(blocks).toHaveLength(2)
  for (const block of blocks) {
    expect(block).toHaveAttribute('aria-hidden', 'true')
  }
})

test('a spinner announces what it is waiting for', () => {
  render(<Spinner>Reading the posting…</Spinner>)

  expect(screen.getByRole('status')).toHaveTextContent('Reading the posting…')
})

test('waiting on the model is announced in words', () => {
  render(<Thinking>Evaluating your answer…</Thinking>)

  expect(screen.getByRole('status')).toHaveTextContent('Evaluating your answer…')
})
