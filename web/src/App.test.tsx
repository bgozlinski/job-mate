import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'

import { App } from './App'

test('the shell renders', () => {
  render(<App />)

  expect(screen.getByRole('heading', { name: 'JobMate' })).toBeInTheDocument()
})
