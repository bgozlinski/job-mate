import { useState } from 'react'
import type { ReactElement, SyntheticEvent } from 'react'
import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react'
import { Link, useNavigate } from 'react-router'

import { CONTROL } from './controls'

/*
 * After Ant Design's pagination, as the Setproduct article on pagination
 * shows it: bare numbers, the current one outlined rather than filled, arrows
 * without words. Every step keeps a transparent border so that the one drawn
 * on hover changes a colour, never the layout. 44px targets on a phone, 36px
 * from sm up.
 */
const STEP =
  'inline-flex size-11 items-center justify-center rounded-control border text-sm ' +
  'tabular-nums sm:size-9 focus-visible:outline-2 focus-visible:outline-offset-2 ' +
  'focus-visible:outline-accent'
const LINK = `${STEP} border-transparent text-ink hover:border-control hover:text-accent`
const CURRENT = `${STEP} border-accent font-semibold text-accent`
const INERT = `${STEP} border-transparent text-ink-faint opacity-50`

/** From how many pages on a list offers to jump to one by its number. */
export const JUMP_FROM = 10

/**
 * The page numbers worth showing: the first, the last, and `radius` either
 * side of the current, with a gap (null) wherever numbers are skipped.
 */
export function pagesAround(page: number, count: number, radius = 1): (number | null)[] {
  const wanted = new Set([1, count, page])

  for (let step = 1; step <= radius; step += 1) {
    wanted.add(page - step)
    wanted.add(page + step)
  }

  const shown = [...wanted].filter((n) => n >= 1 && n <= count).sort((a, b) => a - b)

  return shown.flatMap((n, index) => {
    const previous = shown[index - 1]

    return previous !== undefined && n - previous > 1 ? [null, n] : [n]
  })
}

/**
 * A page number: the digit to the eye, "Page 3" to a screen reader.
 *
 * One string for the reader rather than "Page " beside the digit: an
 * accessible name drops the trailing space and would read "Page3".
 */
function PageNumber({ page }: { page: number }): ReactElement {
  return (
    <>
      <span className="sr-only">{`Page ${String(page)}`}</span>
      <span aria-hidden="true">{page}</span>
    </>
  )
}

/** Previous or next: an arrow to the eye, its name to a screen reader. */
function Arrow({
  to,
  name,
  icon: Icon,
}: {
  to: string | null
  name: string
  icon: typeof ChevronLeftIcon
}): ReactElement {
  const inside = (
    <>
      <span className="sr-only">{name}</span>
      <Icon aria-hidden="true" className="size-4" />
    </>
  )

  return to ? (
    <Link to={to} title={name} className={LINK}>
      {inside}
    </Link>
  ) : (
    <span aria-disabled="true" className={INERT}>
      {inside}
    </span>
  )
}

/** One step of the row: a page number or a gap, and where it is drawn. */
export interface Step {
  page: number | null
  /** Drawn on a phone, below sm. */
  narrow: boolean
  /** Drawn from sm up. */
  wide: boolean
}

/**
 * The row for every width at once: the neighbours of the current page drawn
 * only from sm up, and a gap drawn only on a phone wherever hiding them skips
 * numbers. One list rather than two, so each page is one link to a screen
 * reader and to a test.
 */
export function steps(page: number, count: number): Step[] {
  const narrow = new Set(pagesAround(page, count, 0))
  const row: Step[] = []
  let lastNarrow: number | null = null
  let gapSince = false

  for (const n of pagesAround(page, count)) {
    if (n === null) {
      row.push({ page: null, narrow: true, wide: true })
      gapSince = true
    } else if (narrow.has(n)) {
      if (lastNarrow !== null && n - lastNarrow > 1 && !gapSince) {
        row.push({ page: null, narrow: true, wide: false })
      }
      row.push({ page: n, narrow: true, wide: true })
      lastNarrow = n
      gapSince = false
    } else {
      row.push({ page: n, narrow: false, wide: true })
    }
  }

  return row
}

function shownAt(step: Step): string {
  return step.narrow ? (step.wide ? '' : 'sm:hidden') : 'hidden sm:block'
}

/**
 * Numbered pages under a list: "‹ 1 … 4 5 6 … 12 ›".
 *
 * Links, not buttons, because the page lives in the address: it survives a
 * reload and "back" returns to it. The current page is marked for a screen
 * reader with aria-current, and nothing is drawn for a list of one page. On
 * a phone the neighbours of the current page go, "‹ 1 … 5 … 12 ›", so the
 * row fits at 44px a target; the arrows stay, dimmed where there is no way on.
 */
export function Pagination({
  page,
  count,
  hrefFor,
  label = 'Pages',
}: {
  page: number
  count: number
  hrefFor: (page: number) => string
  label?: string
}): ReactElement | null {
  if (count <= 1) {
    return null
  }

  return (
    <nav aria-label={label}>
      <ul className="flex items-center gap-1">
        <li>
          <Arrow
            to={page > 1 ? hrefFor(page - 1) : null}
            name="Previous page"
            icon={ChevronLeftIcon}
          />
        </li>
        {steps(page, count).map((step, index) =>
          step.page === null ? (
            <li
              key={`gap-${String(index)}`}
              aria-hidden="true"
              className={`px-1 text-ink-faint ${shownAt(step)}`}
            >
              …
            </li>
          ) : (
            <li key={step.page} className={shownAt(step)}>
              {step.page === page ? (
                <span aria-current="page" className={CURRENT}>
                  <PageNumber page={step.page} />
                </span>
              ) : (
                <Link to={hrefFor(step.page)} className={LINK}>
                  <PageNumber page={step.page} />
                </Link>
              )}
            </li>
          ),
        )}
        <li>
          <Arrow
            to={page < count ? hrefFor(page + 1) : null}
            name="Next page"
            icon={ChevronRightIcon}
          />
        </li>
      </ul>
    </nav>
  )
}

/**
 * "Go to [ ] page": jump straight to a page by its number, for a list long
 * enough that clicking through is a chore. A number with no page behind it
 * says so, where the reader typed it, and goes nowhere.
 */
export function GoToPage({
  id,
  count,
  hrefFor,
}: {
  id: string
  count: number
  hrefFor: (page: number) => string
}): ReactElement | null {
  const navigate = useNavigate()
  const [typed, setTyped] = useState('')
  const [wrong, setWrong] = useState<string | null>(null)

  if (count < JUMP_FROM) {
    return null
  }

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()
    const page = Number(typed)

    if (!Number.isInteger(page) || page < 1 || page > count) {
      setWrong(`There is no page ${typed.trim() || '0'}: pages go from 1 to ${String(count)}.`)

      return
    }

    setWrong(null)
    setTyped('')
    void navigate(hrefFor(page))
  }

  return (
    // noValidate: the browser's own check of min and max would stop the form
    // with a bubble of its own, and the message here says more.
    <form
      noValidate
      onSubmit={onSubmit}
      className="flex flex-col items-center gap-1 text-sm text-ink-soft"
    >
      <div className="flex items-center gap-2 whitespace-nowrap">
        <label htmlFor={id}>Go to</label>
        <input
          id={id}
          type="number"
          inputMode="numeric"
          min={1}
          max={count}
          aria-invalid={wrong !== null}
          aria-describedby={wrong ? `${id}-error` : undefined}
          className={`${CONTROL} w-16 py-1 text-center tabular-nums`}
          value={typed}
          onChange={(event) => {
            setTyped(event.target.value)
          }}
        />
        <span aria-hidden="true">page</span>
        {/* Enter is the way in, as in the design this follows; the button
            keeps it a proper form -- one a screen reader can name and every
            browser submits. */}
        <button type="submit" className="sr-only">
          Go
        </button>
      </div>
      {wrong ? (
        <p id={`${id}-error`} role="alert" className="text-xs text-danger">
          {wrong}
        </p>
      ) : null}
    </form>
  )
}

/** The page asked for in the address: a whole number from 1, else the first. */
export function pageFrom(value: string | null): number {
  const page = Number(value)

  return Number.isInteger(page) && page >= 1 ? page : 1
}

/** How many rows a page may hold, as offered to the reader. */
export const PAGE_SIZES = [5, 10, 15, 20] as const

/** The rows on a page unless the reader picks another; what lists had before. */
export const DEFAULT_PAGE_SIZE = 20

/**
 * The page size asked for in the address: one of those offered, else the
 * default. Anything else would reach the API as a limit it may refuse.
 */
export function sizeFrom(value: string | null): number {
  const size = Number(value)

  return (PAGE_SIZES as readonly number[]).includes(size) ? size : DEFAULT_PAGE_SIZE
}

/**
 * The page, at a new size, that still shows the first row the reader had in
 * front of them: row 31 is on page 7 of fives and on page 2 of twenties.
 */
export function pageKeeping(page: number, from: number, to: number): number {
  return Math.floor(((page - 1) * from) / to) + 1
}

/**
 * The search part of a paged list's address: only what differs from the
 * defaults, so the first page at the usual size is the bare address.
 */
export function pagedSearch(page: number, size: number, rest: Record<string, string> = {}): string {
  const query = new URLSearchParams(rest)

  if (page > 1) {
    query.set('page', String(page))
  }

  if (size !== DEFAULT_PAGE_SIZE) {
    query.set('size', String(size))
  }

  const search = query.toString()

  return search ? `?${search}` : ''
}

/**
 * How many rows each page shows, as a "10 / page" select beside the page
 * numbers. Drawn
 * only when there are more rows than the smallest page holds: below that,
 * every choice shows the same list.
 */
export function PageSize({
  id,
  size,
  total,
  onChange,
}: {
  id: string
  size: number
  total: number
  onChange: (size: number) => void
}): ReactElement | null {
  if (total <= Math.min(...PAGE_SIZES)) {
    return null
  }

  return (
    // "10 / page" says it in the select itself; the label is for a screen
    // reader. Never squeezed: beside the page numbers, a shrinking control
    // broke its words onto several lines.
    <div className="shrink-0 whitespace-nowrap">
      <label htmlFor={id} className="sr-only">
        Rows per page
      </label>
      <select
        id={id}
        className={`${CONTROL} w-auto py-1 text-sm tabular-nums`}
        value={size}
        onChange={(event) => {
          onChange(Number(event.target.value))
        }}
      >
        {PAGE_SIZES.map((option) => (
          <option key={option} value={option}>
            {`${String(option)} / page`}
          </option>
        ))}
      </select>
    </div>
  )
}
