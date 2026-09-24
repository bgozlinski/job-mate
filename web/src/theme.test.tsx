import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import { THEME_KEY, chooseTheme, storedTheme } from './theme'
import { ThemeToggle } from './ui'

const root = document.documentElement

beforeEach(() => {
  window.localStorage.clear()
  root.removeAttribute('data-theme')
})

afterEach(() => {
  vi.restoreAllMocks()
})

test('with nothing stored the theme follows the system', () => {
  expect(storedTheme()).toBe('system')
})

test('choosing dark marks the page and remembers it', () => {
  chooseTheme('dark')

  expect(root).toHaveAttribute('data-theme', 'dark')
  expect(storedTheme()).toBe('dark')
})

test('choosing system clears both the mark and the memory', () => {
  chooseTheme('light')
  chooseTheme('system')

  expect(root).not.toHaveAttribute('data-theme')
  expect(window.localStorage.getItem(THEME_KEY)).toBeNull()
})

test('a stored value that is not a theme reads as system', () => {
  window.localStorage.setItem(THEME_KEY, 'purple')

  expect(storedTheme()).toBe('system')
})

test('blocked storage falls back to system instead of failing', () => {
  // A private window or a browser with site data blocked throws on access.
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new Error('blocked')
  })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new Error('blocked')
  })

  expect(storedTheme()).toBe('system')
  expect(() => {
    chooseTheme('dark')
  }).not.toThrow()
  // Not remembered, but still applied for as long as the page is open.
  expect(root).toHaveAttribute('data-theme', 'dark')
})

test('the toggle shows the stored choice as pressed', () => {
  window.localStorage.setItem(THEME_KEY, 'dark')

  render(<ThemeToggle />)

  const group = screen.getByRole('group', { name: 'Colour theme' })
  expect(group).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Dark' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  expect(screen.getByRole('button', { name: 'System' })).toHaveAttribute(
    'aria-pressed',
    'false',
  )
})

test('pressing a choice applies it and moves the pressed state', async () => {
  render(<ThemeToggle />)

  await userEvent.click(screen.getByRole('button', { name: 'Light' }))

  expect(root).toHaveAttribute('data-theme', 'light')
  expect(screen.getByRole('button', { name: 'Light' })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  expect(storedTheme()).toBe('light')
})
