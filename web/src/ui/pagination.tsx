import type { ReactElement } from 'react'
import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react'
import { Link } from 'react-router'

const STEP =
  'inline-flex min-w-8 items-center justify-center gap-1 rounded-control px-2 py-1 ' +
  'text-sm tabular-nums'
const LINK = `${STEP} border border-control bg-raised text-ink hover:border-accent hover:text-accent`
const CURRENT = `${STEP} bg-accent font-semibold text-on-accent`
const INERT = `${STEP} border border-line text-ink-faint`

/**
 * The page numbers worth showing: the first, the last, and the ones either
 * side of the current, with a gap (null) wherever numbers are skipped.
 */
export function pagesAround(page: number, count: number): (number | null)[] {
  const wanted = new Set([1, count, page - 1, page, page + 1])
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

/**
 * Numbered pages under a list: "‹ Previous 1 … 4 5 6 … 12 Next ›".
 *
 * Links, not buttons, because the page lives in the address: it survives a
 * reload and "back" returns to it. The current page is marked for a screen
 * reader with aria-current, and nothing is drawn for a list of one page.
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

  const previous = page > 1 ? page - 1 : null
  const next = page < count ? page + 1 : null

  return (
    <nav aria-label={label}>
      <ul className="flex flex-wrap items-center gap-1">
        <li>
          {previous ? (
            <Link to={hrefFor(previous)} className={LINK}>
              <ChevronLeftIcon aria-hidden="true" className="size-4" />
              Previous
            </Link>
          ) : (
            <span aria-disabled="true" className={INERT}>
              <ChevronLeftIcon aria-hidden="true" className="size-4" />
              Previous
            </span>
          )}
        </li>
        {pagesAround(page, count).map((n, index) =>
          n === null ? (
            <li key={`gap-${String(index)}`} aria-hidden="true" className="px-1 text-ink-faint">
              …
            </li>
          ) : (
            <li key={n}>
              {n === page ? (
                <span aria-current="page" className={CURRENT}>
                  <PageNumber page={n} />
                </span>
              ) : (
                <Link to={hrefFor(n)} className={LINK}>
                  <PageNumber page={n} />
                </Link>
              )}
            </li>
          ),
        )}
        <li>
          {next ? (
            <Link to={hrefFor(next)} className={LINK}>
              Next
              <ChevronRightIcon aria-hidden="true" className="size-4" />
            </Link>
          ) : (
            <span aria-disabled="true" className={INERT}>
              Next
              <ChevronRightIcon aria-hidden="true" className="size-4" />
            </span>
          )}
        </li>
      </ul>
    </nav>
  )
}

/** The page asked for in the address: a whole number from 1, else the first. */
export function pageFrom(value: string | null): number {
  const page = Number(value)

  return Number.isInteger(page) && page >= 1 ? page : 1
}
