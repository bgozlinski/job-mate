import { useState } from 'react'
import type { ReactElement } from 'react'
import { MonitorIcon, MoonIcon, SunIcon } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { THEMES, chooseTheme, storedTheme } from '../theme'
import type { Theme } from '../theme'

const CHOICES: Record<Theme, { label: string; icon: LucideIcon }> = {
  light: { label: 'Light', icon: SunIcon },
  system: { label: 'System', icon: MonitorIcon },
  dark: { label: 'Dark', icon: MoonIcon },
}

/**
 * Light, system or dark, as three buttons of which one is pressed.
 *
 * Buttons with aria-pressed rather than a select: all three choices are
 * visible at once, one click away, and a screen reader announces which one
 * is on. Icons only, to keep the header short -- each button is named by
 * aria-label, and the same word shows as a tooltip on hover. The theme itself
 * is applied by theme.ts, so this only mirrors it.
 */
export function ThemeToggle(): ReactElement {
  const [theme, setTheme] = useState<Theme>(storedTheme)

  return (
    <div
      role="group"
      aria-label="Colour theme"
      className="inline-flex rounded-full bg-sunken p-0.5"
    >
      {THEMES.map((option) => {
        const { label, icon: Icon } = CHOICES[option]

        return (
          <button
            key={option}
            type="button"
            aria-label={label}
            title={label}
            aria-pressed={theme === option}
            onClick={() => {
              chooseTheme(option)
              setTheme(option)
            }}
            className={
              'rounded-full p-1.5 transition-colors ' +
              (theme === option
                ? 'bg-raised text-accent shadow-card'
                : 'text-ink-faint hover:text-accent')
            }
          >
            <Icon aria-hidden="true" className="size-4" />
          </button>
        )
      })}
    </div>
  )
}
