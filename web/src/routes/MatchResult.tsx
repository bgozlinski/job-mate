import type { ReactElement } from 'react'

import type { Match } from '../api/matching'
import { Card, Chip, Meter, Muted } from '../ui'

export function percentage(score: number): string {
  return `${String(Math.round(score * 100))}%`
}

function Terms({
  title,
  terms,
  present,
  evidence,
}: {
  title: string
  terms: string[]
  present: boolean
  evidence?: Record<string, string>
}): ReactElement | null {
  if (terms.length === 0) {
    return null
  }

  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold tracking-wide text-ink-soft uppercase">
        {title} ({terms.length})
      </h3>
      <ul className="flex flex-wrap gap-2">
        {terms.map((term) => (
          // A term with a quote under it takes its own row; the rest flow as
          // tags. Left to flex-wrap alone the two groups end up looking like
          // different kinds of thing by accident.
          <li key={term} className={evidence?.[term] ? 'basis-full' : undefined}>
            <Chip present={present}>{term}</Chip>
            {/* What the model quoted from the resume for a requirement it
                judged met. This is the half that lets a candidate disagree
                with the verdict instead of taking it on trust; it is empty
                for a term matched literally, and empty everywhere when no
                judge is configured. */}
            {evidence?.[term] ? (
              <q className="mt-1 block max-w-prose text-xs text-ink-faint italic">
                {evidence[term]}
              </q>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}

/**
 * One match, shown the same way whether it has just been computed or read
 * back out of the history.
 *
 * The score leads as a hero figure with a meter beside it: one number is what
 * this screen is for, and a single ratio against a limit is a meter rather
 * than a chart. The meter keeps one hue at every value -- a fill that ran red
 * to green would be a diverging encoding, and that is the pair a colour-vision
 * check rejects.
 *
 * suggestions and notes stay two lists. They come back separately on purpose:
 * suggestions are lines to put in the resume, notes are remarks about it, and
 * a page that ran them together would present "the resume does not evidence
 * Docker" as a bullet point to paste into it.
 */
export function MatchResult({ match }: { match: Match }): ReactElement {
  return (
    <article aria-label="Match result" className="flex flex-col gap-8">
      <Card className="flex flex-col gap-4">
        {/* One heading, not a number floating beside one. The hero figure is
            a span inside it, so the score reads as display type while the
            heading's accessible name stays the whole sentence -- somebody
            navigating by headings hears "75% match, Python Developer", not
            a bare "75%". */}
        <h2 className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-5xl font-bold tracking-tight text-accent">
            {percentage(match.score)}
          </span>{' '}
          <span className="text-lg font-medium">
            match
            {match.document_title ? ` · ${match.document_title}` : null}
          </span>
        </h2>

        <Muted>
          {match.matched_keywords.length} of{' '}
          {match.matched_keywords.length + match.missing_keywords.length}{' '}
          requirements covered
        </Muted>

        <Meter value={match.score} label="Requirements covered" />
      </Card>

      <div className="grid gap-8 md:grid-cols-2">
        <Terms
          title="Covered"
          terms={match.matched_keywords}
          present
          evidence={match.matched_evidence}
        />
        <Terms title="Missing" terms={match.missing_keywords} present={false} />
      </div>

      {match.suggestions.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold tracking-wide text-ink-soft uppercase">
            Suggested bullet points
          </h3>
          <ul className="flex flex-col gap-2">
            {match.suggestions.map((suggestion) => (
              <li key={suggestion}>
                <Card className="max-w-prose text-sm">{suggestion}</Card>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {match.notes.length > 0 ? (
        <section className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold tracking-wide text-ink-soft uppercase">
            Notes on the resume
          </h3>
          <ul className="flex max-w-prose list-disc flex-col gap-1 pl-5 text-sm text-ink-soft">
            {match.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* Not decoration: the API returns which fragments the suggestions were
          built from so an answer can be checked against what the model
          actually saw (NFR-2). The ids themselves would be noise on a page;
          that there were any, and how many, is the part a reader can use. */}
      <Muted>
        Grounded in {String(match.retrieved_chunk_ids.length)} fragments of the
        posting.
      </Muted>
    </article>
  )
}
