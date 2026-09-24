import { useState } from 'react'
import type { ReactElement } from 'react'

import { THEMES, chooseTheme, storedTheme } from '../theme'
import type { Theme } from '../theme'

const LABELS: Record<Theme, string> = {
  light: 'Light',
  system: 'System',
  dark: 'Dark',
}

/**
 * Light, system or dark, as three buttons of which one is pressed.
 *
 * Buttons with aria-pressed rather than a select: all three choices are
 * visible at once, one click away, and a screen reader announces which one
 * is on. The theme itself is applied by theme.ts, so this only mirrors it.
 */
export function ThemeToggle(): ReactElement {
  const [theme, setTheme] = useState<Theme>(storedTheme)

  return (
    <div
      role="group"
      aria-label="Colour theme"
      className="inline-flex rounded-full bg-sunken p-0.5"
    >
      {THEMES.map((option) => (
        <button
          key={option}
          type="button"
          aria-pressed={theme === option}
          onClick={() => {
            chooseTheme(option)
            setTheme(option)
          }}
          className={
            'rounded-full px-2.5 py-1 text-xs font-semibold transition-colors ' +
            (theme === option
              ? 'bg-raised text-ink shadow-card'
              : 'text-ink-soft hover:text-accent')
          }
        >
          {LABELS[option]}
        </button>
      ))}
    </div>
  )
}
