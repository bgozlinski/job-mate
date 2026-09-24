/**
 * The colour theme the person chose, and applying it.
 *
 * 'system' is the default and means "follow the operating system": the page
 * then carries no data-theme at all and styles.css decides with a media
 * query, so nothing here has to listen for the system changing its mind.
 *
 * The choice is kept in localStorage, which is this browser's convenience and
 * nothing more: it can be missing (a private window), it can throw (storage
 * blocked), and either way the page falls back to 'system' rather than
 * failing.
 *
 * index.html repeats the key and the allowed values in a few lines of inline
 * script, so the theme is set before the first paint. Change one, change both.
 */

export type Theme = 'light' | 'dark' | 'system'

export const THEMES: readonly Theme[] = ['light', 'system', 'dark']

export const THEME_KEY = 'jobmate-theme'

function isTheme(value: unknown): value is Theme {
  return value === 'light' || value === 'dark' || value === 'system'
}

/** The theme stored in this browser, or 'system' when there is none. */
export function storedTheme(): Theme {
  try {
    const value = window.localStorage.getItem(THEME_KEY)

    return isTheme(value) ? value : 'system'
  } catch {
    return 'system'
  }
}

/** Put a theme on the page: an attribute for light or dark, none for system. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement

  if (theme === 'system') {
    root.removeAttribute('data-theme')
  } else {
    root.setAttribute('data-theme', theme)
  }
}

/** Apply a theme and remember it, if this browser lets us. */
export function chooseTheme(theme: Theme): void {
  applyTheme(theme)

  try {
    if (theme === 'system') {
      window.localStorage.removeItem(THEME_KEY)
    } else {
      window.localStorage.setItem(THEME_KEY, theme)
    }
  } catch {
    // Not remembered, but applied: the choice holds until the page reloads.
  }
}
