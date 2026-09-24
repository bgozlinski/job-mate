/**
 * The handful of shapes every screen is built from, imported from one place.
 *
 * They exist because of what Tailwind costs at this size: screens repeating the
 * same dozen utility classes for a button or a labelled field is a diff nobody
 * can review and a change nobody can make in one place. Layout stays in utility
 * classes at the call site, where it differs; anything repeated lives here.
 *
 * Each one renders the element it stands for -- a button is a <button>, a field
 * is a <label> and a control sharing an id -- because the tests find them by
 * role and label. If a restyle here makes one of those tests fail, it changed
 * behaviour rather than appearance.
 *
 * Split by kind so no file holds everything: controls, surfaces, data, and
 * feedback, plus the theme toggle.
 */

export { Button, CONTROL, Field } from './controls'
export { Chip, Meter } from './data'
export { Alert, Status } from './feedback'
export { Card, Muted, PageTitle } from './surfaces'
export { ThemeToggle } from './ThemeToggle'
